const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type EnquiryCreate = {
  source: "email" | "website" | "messaging";
  sender_name: string;
  sender_email?: string;
  message: string;
};

export async function createEnquiry(data: EnquiryCreate) {
  const res = await fetch(`${API_URL}/api/v1/enquiries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to create enquiry");
  }
  return res.json();
}

export async function listEnquiries(params?: Record<string, string>) {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  const res = await fetch(`${API_URL}/api/v1/enquiries${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch enquiries");
  return res.json();
}

export async function listActions(status?: string) {
  const qs = status ? `?status=${status}` : "";
  const res = await fetch(`${API_URL}/api/v1/actions${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch actions");
  return res.json();
}

export async function approveAction(id: string) {
  const res = await fetch(`${API_URL}/api/v1/actions/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: "demo_user" }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Approve failed");
  }
  return res.json();
}

export async function rejectAction(id: string) {
  const res = await fetch(`${API_URL}/api/v1/actions/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: "demo_user" }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Reject failed");
  }
  return res.json();
}

export async function getHealth() {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function listAudit(limit = 50) {
  const res = await fetch(`${API_URL}/api/v1/audit?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch audit");
  return res.json();
}

export async function listContacts() {
  const res = await fetch(`${API_URL}/api/v1/crm/contacts`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function getInsightsSummary() {
  const res = await fetch(`${API_URL}/api/v1/insights/summary`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch insights summary");
  return res.json();
}

export async function getInsightsRecent(params?: Record<string, string>) {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  const res = await fetch(`${API_URL}/api/v1/insights/recent${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch recent insights");
  return res.json();
}

export async function getEnquiryInsight(id: string) {
  const res = await fetch(`${API_URL}/api/v1/insights/enquiry/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch insight");
  return res.json();
}

export async function listTeams() {
  const res = await fetch(`${API_URL}/api/v1/teams`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function deleteEnquiry(id: string) {
  const res = await fetch(`${API_URL}/api/v1/enquiries/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Delete failed");
  }
  return true;
}

export async function deleteContact(id: string) {
  const res = await fetch(`${API_URL}/api/v1/crm/contacts/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Delete failed");
  }
  return true;
}
