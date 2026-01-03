#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 显示姓氏更新器 - 后台守护进程
负责持续运行并更新所有账号的显示姓氏
"""
import os
import sys
import json
import asyncio
import logging
import signal
from datetime import datetime
from pathlib import Path
from typing import Dict

from telethon import TelegramClient
from telethon.tl.functions.account import UpdateProfileRequest

# 配置日志 - 仅输出到终端
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 全局变量
SESSIONS_DIR = Path('/app/data/sessions')
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = SESSIONS_DIR / 'config.json'
PID_FILE = Path('/app/data/daemon.pid')

# 存储活动的客户端和任务
active_clients: Dict[str, TelegramClient] = {}
active_tasks: Dict[str, asyncio.Task] = {}

# 全局标志
running = True


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        self.config_file = CONFIG_FILE
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
        return {'accounts': {}}
    
    def get_all_accounts(self) -> dict:
        """获取所有账号"""
        return self.config['accounts']
    
    def reload(self):
        """重新加载配置"""
        self.config = self._load_config()


config_manager = ConfigManager()


async def update_name_task(phone: str, client: TelegramClient):
    """更新显示姓氏的任务 - 每分钟更新一次"""
    logger.info(f"📝 [{phone}] 开始自动更新任务")
    
    # 立即执行一次更新
    try:
        now = datetime.now()
        hour = now.strftime("%H")
        minute = now.strftime("%M")
        last_name = f"{hour}:{minute} UTC+8"
        await client(UpdateProfileRequest(last_name=last_name))
        logger.info(f"✅ [{phone}] 初始更新 -> {last_name}")
    except Exception as e:
        logger.error(f"❌ [{phone}] 初始更新失败: {e}")
    
    while running:
        try:
            # 计算到下一分钟的秒数
            now = datetime.now()
            seconds_to_next_minute = 60 - now.second
            
            # 等待到下一分钟
            await asyncio.sleep(seconds_to_next_minute)
            
            if not running:
                break
            
            # 获取当前时间
            now = datetime.now()
            hour = now.strftime("%H")
            minute = now.strftime("%M")
            
            # 格式化为 HH:MM UTC+8
            last_name = f"{hour}:{minute} UTC+8"
            
            # 更新 Telegram 显示姓氏（更新到 Last Name）
            await client(UpdateProfileRequest(last_name=last_name))
            
            logger.info(f"✅ [{phone}] 已更新 -> {last_name}")
        
        except asyncio.CancelledError:
            logger.info(f"⏹️  [{phone}] 更新任务已停止")
            break
        except Exception as e:
            logger.error(f"❌ [{phone}] 更新失败: {e}")
            # 如果出错，等待10秒后重试
            await asyncio.sleep(10)


async def start_account(phone: str, account: dict):
    """启动单个账号"""
    try:
        session_path = str(SESSIONS_DIR / phone)
        client = TelegramClient(session_path, account['api_id'], account['api_hash'])
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.warning(f"⚠️  账号未授权，跳过: {phone}")
            return False
        
        # 获取用户信息
        me = await client.get_me()
        logger.info(f"👤 加载账号: {me.first_name} (@{me.username or 'unknown'}) - {phone}")
        
        # 存储客户端
        active_clients[phone] = client
        
        # 启动更新任务
        task = asyncio.create_task(update_name_task(phone, client))
        active_tasks[phone] = task
        
        logger.info(f"🚀 已启动账号: {phone}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 启动账号失败 {phone}: {e}")
        return False


async def start_all_accounts():
    """启动所有账号"""
    accounts = config_manager.get_all_accounts()
    
    if not accounts:
        logger.info("📭 没有配置的账号")
        return
    
    logger.info(f"🔄 正在加载 {len(accounts)} 个账号...")
    
    success_count = 0
    for phone, account in accounts.items():
        if await start_account(phone, account):
            success_count += 1
    
    logger.info(f"✅ 成功启动 {success_count}/{len(accounts)} 个账号")


async def stop_account(phone: str):
    """停止单个账号"""
    if phone in active_tasks:
        active_tasks[phone].cancel()
        try:
            await active_tasks[phone]
        except asyncio.CancelledError:
            pass
        del active_tasks[phone]
        logger.info(f"⏹️  已停止账号: {phone}")
    
    if phone in active_clients:
        try:
            await active_clients[phone].disconnect()
        except:
            pass
        del active_clients[phone]


async def reload_accounts():
    """重新加载账号（用于配置文件更新后）"""
    logger.info("🔄 重新加载配置...")
    
    # 重新加载配置
    config_manager.reload()
    new_accounts = config_manager.get_all_accounts()
    
    # 停止已删除的账号
    current_phones = set(active_clients.keys())
    new_phones = set(new_accounts.keys())
    
    removed_phones = current_phones - new_phones
    for phone in removed_phones:
        logger.info(f"🗑️  删除账号: {phone}")
        await stop_account(phone)
    
    # 启动新增的账号
    added_phones = new_phones - current_phones
    for phone in added_phones:
        logger.info(f"➕ 新增账号: {phone}")
        await start_account(phone, new_accounts[phone])
    
    logger.info("✅ 配置重新加载完成")


async def monitor_config_changes():
    """监控配置文件变化"""
    last_mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else 0
    
    while running:
        try:
            await asyncio.sleep(5)  # 每5秒检查一次
            
            if not running:
                break
            
            if CONFIG_FILE.exists():
                current_mtime = CONFIG_FILE.stat().st_mtime
                if current_mtime != last_mtime:
                    logger.info("📝 检测到配置文件变化")
                    last_mtime = current_mtime
                    await reload_accounts()
        
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"监控配置文件失败: {e}")


def write_pid():
    """写入 PID 文件"""
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_pid():
    """删除 PID 文件"""
    if PID_FILE.exists():
        PID_FILE.unlink()


async def shutdown():
    """优雅关闭"""
    global running
    running = False
    
    logger.info("🛑 正在停止所有任务...")
    
    # 取消所有更新任务
    for phone, task in list(active_tasks.items()):
        task.cancel()
    
    # 等待任务完成
    if active_tasks:
        await asyncio.gather(*active_tasks.values(), return_exceptions=True)
    
    # 断开所有客户端
    for phone, client in list(active_clients.items()):
        try:
            await client.disconnect()
            logger.info(f"🔌 已断开: {phone}")
        except Exception as e:
            logger.error(f"断开连接失败 {phone}: {e}")
    
    active_tasks.clear()
    active_clients.clear()
    
    remove_pid()
    logger.info("✅ 所有资源已清理，守护进程已停止")


def signal_handler(signum, frame):
    """信号处理器"""
    global running
    logger.info(f"收到信号 {signum}")
    running = False


async def main():
    """主函数"""
    global running
    
    logger.info("=" * 60)
    logger.info("🤖 Telegram 显示姓氏自动更新守护进程启动")
    logger.info("=" * 60)
    
    # 写入 PID
    write_pid()
    logger.info(f"📝 PID: {os.getpid()}")
    
    # 注册信号处理
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # 启动所有账号
        await start_all_accounts()
        
        # 启动配置文件监控
        monitor_task = asyncio.create_task(monitor_config_changes())
        
        logger.info("✅ 守护进程运行中...")
        logger.info("💡 使用 'tg-cli' 命令管理账号")
        
        # 主循环 - 简单地检查运行状态
        while running:
            await asyncio.sleep(1)
        
        # 取消监控任务
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        
        # 执行关闭清理
        await shutdown()
        
    except KeyboardInterrupt:
        logger.info("⚠️  收到键盘中断")
        await shutdown()
    except Exception as e:
        logger.error(f"❌ 守护进程异常: {e}", exc_info=True)
        await shutdown()
        raise


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序退出")
    except Exception as e:
        logger.error(f"程序崩溃: {e}", exc_info=True)
        remove_pid()
        sys.exit(1)
