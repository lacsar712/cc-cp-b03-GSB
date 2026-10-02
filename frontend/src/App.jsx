import { useCallback, useEffect, useState } from "preact/hooks";

const TOKEN_KEY = "coldchain_token";
const USER_KEY = "coldchain_user";

const STATUS_TEXT = {
  unconfirmed: "待确认",
  pending: "待认领",
  processing: "处理中",
  done: "已完成",
};

const ACTION_TEXT = {
  created: "建单",
  confirmed: "确认",
};

function fmtTime(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

function verdictClass(v, status) {
  if (v === "合格") return "tag pass";
  if (v === "超温") return "tag fail";
  return "tag wait";
}

function displayVerdict(row) {
  if (row.verdict) return row.verdict;
  return STATUS_TEXT[row.status] || "—";
}

export function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch {
      return null;
    }
  });
  const [view, setView] = useState("desk"); // desk | confirm
  const [loginForm, setLoginForm] = useState({ username: "logger", password: "log123456" });
  const [submitForm, setSubmitForm] = useState({ probe_id: "", temp_c: "" });
  const [rows, setRows] = useState([]);
  const [flow, setFlow] = useState([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirmingId, setConfirmingId] = useState(null);

  const authHeaders = useCallback(() => {
    const h = { "Content-Type": "application/json" };
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, [token]);

  const loadReadings = useCallback(async () => {
    if (!token) return;
    const res = await fetch("/api/readings", { headers: authHeaders() });
    if (!res.ok) {
      setError("加载列表失败，请重新登录");
      return;
    }
    setRows(await res.json());
  }, [token, authHeaders]);

  const loadFlow = useCallback(async () => {
    if (!token) return;
    const res = await fetch("/api/flow", { headers: authHeaders() });
    if (res.ok) setFlow(await res.json());
  }, [token, authHeaders]);

  useEffect(() => {
    loadReadings();
    if (view === "confirm") loadFlow();
    if (!token) return undefined;
    const t = setInterval(() => {
      loadReadings();
      if (view === "confirm") loadFlow();
    }, 3000);
    return () => clearInterval(t);
  }, [loadReadings, loadFlow, view, token]);

  async function onLogin(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm),
      });
      if (!res.ok) {
        setError("用户名或密码错误");
        return;
      }
      const data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(
        USER_KEY,
        JSON.stringify({ username: data.username, role: data.role })
      );
      setToken(data.access_token);
      setUser({ username: data.username, role: data.role });
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
    setRows([]);
    setFlow([]);
    setView("desk");
  }

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setMsg("");
    setLoading(true);
    try {
      const res = await fetch("/api/readings", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          probe_id: submitForm.probe_id,
          temp_c: parseFloat(submitForm.temp_c),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "提交失败");
        return;
      }
      setMsg(data.message || "已提交");
      setSubmitForm({ probe_id: "", temp_c: "" });
      await loadReadings();
      if (view === "confirm") await loadFlow();
    } finally {
      setLoading(false);
    }
  }

  async function onConfirm(row) {
    setError("");
    setMsg("");
    setConfirmingId(row.id);
    try {
      const res = await fetch(`/api/readings/${row.id}/confirm`, {
        method: "POST",
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "确认失败");
        return;
      }
      setMsg(data.message || `第 ${row.id} 单已确认`);
      await Promise.all([loadReadings(), loadFlow()]);
    } finally {
      setConfirmingId(null);
    }
  }

  if (!token) {
    return (
      <div class="wrap">
        <h1>冷链探头超温台</h1>
        <p class="sub">
          记录员提交探头编号与摄氏温度，入队后须由<b>另一名记录员</b>双岗确认，后台工人方可认领并判定。
        </p>
        <div class="card">
          <form onSubmit={onLogin}>
            <div class="row">
              <label>
                用户名
                <input
                  value={loginForm.username}
                  onInput={(e) =>
                    setLoginForm({ ...loginForm, username: e.target.value })
                  }
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={loginForm.password}
                  onInput={(e) =>
                    setLoginForm({ ...loginForm, password: e.target.value })
                  }
                />
              </label>
              <button type="submit" disabled={loading}>
                登录
              </button>
            </div>
            {error && <p class="err">{error}</p>}
          </form>
          <p class="sub" style={{ marginBottom: 0 }}>
            记录员 logger / log123456 · 记录员 logger2 / log2123456 · 观察岗 watcher / watch123456
          </p>
        </div>
      </div>
    );
  }

  const isWriter = user?.role === "writer";
  const unconfirmed = rows.filter((r) => r.status === "unconfirmed");
  const confirmed = rows.filter((r) => r.confirmed_by);

  return (
    <div class="wrap">
      <div class="topbar">
        <div>
          <h1>冷链探头超温台</h1>
          <p class="sub">温度不超过 8℃ 为合格，否则为超温；入队须双岗确认后方可认领。</p>
        </div>
        <div class="user">
          {user?.username}（{isWriter ? "记录员" : "观察岗"}）
          <button type="button" class="secondary" style={{ marginLeft: "0.5rem" }} onClick={logout}>
            退出
          </button>
        </div>
      </div>

      <div class="nav">
        <button
          type="button"
          class={view === "desk" ? "active" : "ghost"}
          onClick={() => { setView("desk"); setError(""); setMsg(""); }}
        >
          读数台
        </button>
        <button
          type="button"
          class={view === "confirm" ? "active" : "ghost"}
          onClick={() => { setView("confirm"); setError(""); setMsg(""); loadFlow(); }}
        >
          双岗确认
        </button>
      </div>

      {error && <p class="err">{error}</p>}
      {msg && <p class="ok">{msg}</p>}

      {view === "desk" && (
        <>
          {isWriter ? (
            <div class="card">
              <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>提交读数</h2>
              <form onSubmit={onSubmit}>
                <div class="row">
                  <label>
                    探头编号
                    <input
                      required
                      value={submitForm.probe_id}
                      onInput={(e) =>
                        setSubmitForm({ ...submitForm, probe_id: e.target.value })
                      }
                      placeholder="例如 探头C03"
                    />
                  </label>
                  <label>
                    温度（℃）
                    <input
                      required
                      type="number"
                      step="0.1"
                      value={submitForm.temp_c}
                      onInput={(e) =>
                        setSubmitForm({ ...submitForm, temp_c: e.target.value })
                      }
                    />
                  </label>
                  <button type="submit" disabled={loading}>
                    提交
                  </button>
                </div>
              </form>
            </div>
          ) : (
            <p class="sub">观察岗仅可翻看单据与确认流水，不可建单、不可确认。</p>
          )}

          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>读数列表</h2>
            <table>
              <thead>
                <tr>
                  <th>编号</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>结论</th>
                  <th>说明</th>
                  <th>状态</th>
                  <th>建单人</th>
                  <th>确认人</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} class={r.status === "unconfirmed" ? "row-unconfirmed" : ""}>
                    <td>{r.id}</td>
                    <td>{r.probe_id}</td>
                    <td>{r.temp_c}</td>
                    <td>
                      <span class={verdictClass(r.verdict, r.status)}>
                        {displayVerdict(r)}
                      </span>
                    </td>
                    <td>{r.reason || "—"}</td>
                    <td>{STATUS_TEXT[r.status] || r.status}</td>
                    <td>{r.created_by}</td>
                    <td>{r.confirmed_by || "—"}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colspan="8">暂无数据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {view === "confirm" && (
        <>
          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
              待确认区
              <span class="count">{unconfirmed.length}</span>
            </h2>
            <table>
              <thead>
                <tr>
                  <th>编号</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>建单人</th>
                  <th>建单时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {unconfirmed.map((r) => {
                  const own = r.created_by === user?.username;
                  return (
                    <tr key={r.id}>
                      <td>{r.id}</td>
                      <td>{r.probe_id}</td>
                      <td>{r.temp_c}</td>
                      <td>{r.created_by}{own && <span class="self">（本人建单）</span>}</td>
                      <td>{fmtTime(r.created_at)}</td>
                      <td>
                        {!isWriter ? (
                          <span class="muted">观察岗不可确认</span>
                        ) : own ? (
                          <span class="muted">须另一名记录员确认</span>
                        ) : (
                          <button
                            type="button"
                            class="confirm-btn"
                            disabled={confirmingId === r.id}
                            onClick={() => onConfirm(r)}
                          >
                            {confirmingId === r.id ? "确认中…" : "双岗确认"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {unconfirmed.length === 0 && (
                  <tr>
                    <td colspan="6">暂无待确认单据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
              已确认区
              <span class="count">{confirmed.length}</span>
            </h2>
            <table>
              <thead>
                <tr>
                  <th>编号</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>建单人</th>
                  <th>确认人</th>
                  <th>确认时间</th>
                  <th>当前状态</th>
                </tr>
              </thead>
              <tbody>
                {confirmed.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{r.probe_id}</td>
                    <td>{r.temp_c}</td>
                    <td>{r.created_by}</td>
                    <td>{r.confirmed_by}</td>
                    <td>{fmtTime(r.confirmed_at)}</td>
                    <td>{STATUS_TEXT[r.status] || r.status}</td>
                  </tr>
                ))}
                {confirmed.length === 0 && (
                  <tr>
                    <td colspan="7">暂无已确认单据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>确认流水</h2>
            <table>
              <thead>
                <tr>
                  <th>流水号</th>
                  <th>时间</th>
                  <th>动作</th>
                  <th>单据</th>
                  <th>操作人</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {flow.map((f) => (
                  <tr key={f.id}>
                    <td>{f.id}</td>
                    <td>{fmtTime(f.created_at)}</td>
                    <td>
                      <span class={f.action === "created" ? "tag wait" : "tag pass"}>
                        {ACTION_TEXT[f.action] || f.action}
                      </span>
                    </td>
                    <td>#{f.reading_id} {f.probe_id} {f.temp_c}℃</td>
                    <td>{f.actor}</td>
                    <td>{f.detail || "—"}</td>
                  </tr>
                ))}
                {flow.length === 0 && (
                  <tr>
                    <td colspan="6">暂无流水</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
