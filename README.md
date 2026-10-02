# 冷链探头超温台

记录员上报探头编号与摄氏温度，入队后须由**另一名记录员双岗确认**，后台工人方可认领先决；按 **8℃** 上限判定 **合格** 或 **超温**。

## 双岗确认规则

1. 建单后单据状态为 `unconfirmed`（待确认），须另一名记录员确认后才转为 `pending`（待认领）。
2. 建单人**不能**确认自己的单，系统返回 403，须切换另一名记录员账号确认。
3. 未确认前，后台工人认领队列跳过该单（`status='pending' AND confirmed_by IS NOT NULL`）；确认后才可领到。
4. 建单、确认两个动作都写 `confirm_flow` 流水；状态翻转与流水写入在**同一事务**一次落库，禁止半截成功。
5. 观察岗（watcher）可翻看单据与确认流水，但不可建单、不可确认。

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
| logger | log123456 | 记录员，可建单、可确认他人单据 |
| logger2 | log2123456 | 记录员（双岗用），可建单、可确认他人单据 |
| watcher | watch123456 | 观察岗，只可翻看单据与确认流水 |

> 双岗流程：用 logger 建单 → 退出登录 → 用 logger2 确认 → 后台工人随后认领。

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
