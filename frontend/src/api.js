export async function api(path, body, method) {
  const token = sessionStorage.getItem("agentguard-token");
  const response = await fetch("/api/" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}
export const money = (n) => (n == null ? "Unknown" : `$${n.toFixed(5)}`);
export const percent = (n) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);
export const latency = (n) => (n == null ? "—" : `${n.toFixed(1)} ms`);
export const date = (value) => new Date(value).toLocaleString();
