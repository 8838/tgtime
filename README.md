介绍：Telegram的Last Name(姓氏)实时显示为当前时间，每分钟更新一次。支持添加多个TG账户

说明：docker环境，准备API ID 和 API Hash（从 https://my.telegram.org/apps 获取）

拉取文件

```
git clone https://github.com/8838/tgtime.git
```

```
cd tgtime
```

构建镜像并启动容器

```
docker compose up -d --build
```

进入容器并添加账户

```
docker exec -it tgtime tg-cli add
```

其他更多命令查看帮助
```
docker exec -it tgtime tg-cli help
```
