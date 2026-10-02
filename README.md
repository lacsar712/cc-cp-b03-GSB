# 冷链探头超温台

记录员上报探头编号与摄氏温度，**建单入队后须另一名记录员在「双岗确认」页点确认**，后台工人才用数据库行锁认领，按 **8℃** 上限判定 **合格** 或 **超温**。建单与确认都会写入确认流水，确认动作与流水在同一事务落库。顶栏「双岗确认」落地页分待确认区、已确认区与确认流水。

## 技术栈

| 层 | 选型 |
|----|------|
| 接口 | Python aiohttp + asyncpg |
| 工人 | `worker.py`（psycopg，`FOR UPDATE SKIP LOCKED`） |
| 页面 | Preact + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3197 |
| 接口 | http://localhost:8197 |
| PostgreSQL | localhost:54397（库名 `coldchain`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| logger | log123456 | 记录员，可提交读数、确认他人建的单 |
| logger2 | log223456 | 记录员，同上（建单人不能确认自己的单，需另一名记录员） |
| watcher | watch123456 | 观察岗，只读列表与确认流水，不可建单不可确认 |

## 启动

```bash
cd projects/18-coldchain-probe-desk
docker compose up --build
```

健康检查：`GET http://localhost:8197/api/health` → `{"status":"ok","service":"coldchain-probe-desk"}`

## 种子数据

| 探头 | 温度 | 结论 |
|------|------|------|
| 探头A01 | 4.2℃ | 合格 |
| 探头B02 | 12.5℃ | 超温 |

## 本地开发（可选）

```bash
# 需本机 PostgreSQL 或仅起 db 容器
cd backend && pip install -r requirements.txt && python api.py
cd backend && python worker.py
cd frontend && npm install && npm run dev
```

接口进程默认监听容器内 **8000**，对外映射 **8197**。
