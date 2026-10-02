import { useCallback, useEffect, useState } from "preact/hooks";

const TOKEN_KEY = "coldchain_token";
const USER_KEY = "coldchain_user";

function verdictClass(v, status) {
  if (v === "合格") return "tag pass";
  if (v === "超温") return "tag fail";
  if (status === "pending" || status === "processing") return "tag wait";
  return "tag wait";
}

function displayVerdict(row) {
  if (row.verdict) return row.verdict;
  if (row.status === "pending") return "待处理";
  if (row.status === "processing") return "处理中";
  return "—";
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

const ACTION_LABEL = { create: "建单", confirm: "确认" };

export function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch {
      return null;
    }
  });
  const [loginForm, setLoginForm] = useState({ username: "logger", password: "log123456" });
  const [submitForm, setSubmitForm] = useState({ probe_id: "", temp_c: "" });
  const [view, setView] = useState("desk");
  const [rows, setRows] = useState([]);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

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

  const loadEvents = useCallback(async () => {
    if (!token) return;
    const res = await fetch("/api/events", { headers: authHeaders() });
    if (res.ok) setEvents(await res.json());
  }, [token, authHeaders]);

  useEffect(() => {
    loadReadings();
    loadEvents();
    if (!token) return undefined;
    const t = setInterval(() => {
      loadReadings();
      loadEvents();
    }, 3000);
    return () => clearInterval(t);
  }, [loadReadings, loadEvents, token]);

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
    setEvents([]);
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
      await Promise.all([loadReadings(), loadEvents()]);
    } finally {
      setLoading(false);
    }
  }

  async function onConfirm(id) {
    setError("");
    setMsg("");
    setLoading(true);
    try {
      const res = await fetch(`/api/readings/${id}/confirm`, {
        method: "POST",
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "确认失败");
        return;
      }
      setMsg(data.message || "已确认");
      await Promise.all([loadReadings(), loadEvents()]);
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div class="wrap">
        <h1>冷链探头超温台</h1>
        <p class="sub">
          记录员提交读数后，需另一名记录员在「双岗确认」页点确认，工人才会认领判定。
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
            记录员 logger / log123456 · logger2 / log223456 · 观察岗 watcher / watch123456
          </p>
        </div>
      </div>
    );
  }

  const isWriter = user?.role === "writer";
  const pendingRows = rows.filter((r) => !r.confirmed_by);
  const confirmedRows = rows.filter((r) => r.confirmed_by);

  function confirmCell(r) {
    if (!isWriter) return <span class="hint">观察岗只读</span>;
    if (r.created_by === user?.username)
      return <span class="hint">本人建单，需另一名记录员确认</span>;
    return (
      <button type="button" disabled={loading} onClick={() => onConfirm(r.id)}>
        确认
      </button>
    );
  }

  return (
    <div class="wrap">
      <div class="topbar">
        <div>
          <h1>冷链探头超温台</h1>
          <p class="sub" style={{ marginBottom: 0 }}>
            建单后须另一名记录员确认，工人才会认领；温度不超过 8℃ 为合格。
          </p>
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
          class={view === "desk" ? "tab active" : "tab"}
          onClick={() => setView("desk")}
        >
          读数台
        </button>
        <button
          type="button"
          class={view === "confirm" ? "tab active" : "tab"}
          onClick={() => setView("confirm")}
        >
          双岗确认
        </button>
      </div>

      {view === "desk" && (
        <div>
          {isWriter && (
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
                {error && <p class="err">{error}</p>}
                {msg && <p class="ok">{msg}</p>}
              </form>
            </div>
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
                  <th>确认</th>
                  <th>状态</th>
                  <th>提交人</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{r.probe_id}</td>
                    <td>{r.temp_c}</td>
                    <td>
                      <span class={verdictClass(r.verdict, r.status)}>
                        {displayVerdict(r)}
                      </span>
                    </td>
                    <td>{r.reason || "—"}</td>
                    <td>
                      {r.confirmed_by ? (
                        <span class="tag pass">已确认·{r.confirmed_by}</span>
                      ) : (
                        <span class="tag wait">待确认</span>
                      )}
                    </td>
                    <td>{r.status}</td>
                    <td>{r.created_by}</td>
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
        </div>
      )}

      {view === "confirm" && (
        <div>
          {error && <p class="err">{error}</p>}
          {msg && <p class="ok">{msg}</p>}

          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>待确认区</h2>
            <table>
              <thead>
                <tr>
                  <th>单号</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>提交人</th>
                  <th>提交时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {pendingRows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{r.probe_id}</td>
                    <td>{r.temp_c}</td>
                    <td>{r.created_by}</td>
                    <td>{fmtTime(r.created_at)}</td>
                    <td>{confirmCell(r)}</td>
                  </tr>
                ))}
                {pendingRows.length === 0 && (
                  <tr>
                    <td colspan="6">暂无待确认的单</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>已确认区</h2>
            <table>
              <thead>
                <tr>
                  <th>单号</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>结论</th>
                  <th>提交人</th>
                  <th>确认人</th>
                  <th>确认时间</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {confirmedRows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{r.probe_id}</td>
                    <td>{r.temp_c}</td>
                    <td>
                      <span class={verdictClass(r.verdict, r.status)}>
                        {displayVerdict(r)}
                      </span>
                    </td>
                    <td>{r.created_by}</td>
                    <td>{r.confirmed_by}</td>
                    <td>{fmtTime(r.confirmed_at)}</td>
                    <td>{r.status}</td>
                  </tr>
                ))}
                {confirmedRows.length === 0 && (
                  <tr>
                    <td colspan="8">暂无已确认的单</td>
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
                  <th>时间</th>
                  <th>单号</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>动作</th>
                  <th>操作人</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.id}>
                    <td>{fmtTime(ev.created_at)}</td>
                    <td>{ev.reading_id}</td>
                    <td>{ev.probe_id}</td>
                    <td>{ev.temp_c}</td>
                    <td>
                      <span class={ev.action === "confirm" ? "tag pass" : "tag wait"}>
                        {ACTION_LABEL[ev.action] || ev.action}
                      </span>
                    </td>
                    <td>{ev.actor}</td>
                  </tr>
                ))}
                {events.length === 0 && (
                  <tr>
                    <td colspan="6">暂无流水</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
