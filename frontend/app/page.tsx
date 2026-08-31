"use client";

import { useEffect, useState } from "react";
import { createEnquiry, listActions, approveAction, rejectAction, getHealth, listEnquiries, listAudit, listContacts } from "@/lib/api";
import { Inbox, Check, X, Clock, ArrowRight, Sparkles } from "lucide-react";

type Toast = { id: string; message: string; type: "success" | "error" | "info" };

const TABS = [
  { id: "ingest", label: "New" },
  { id: "queue", label: "Queue" },
  { id: "enquiries", label: "History" },
  { id: "audit", label: "Log" },
  { id: "crm", label: "Contacts" },
] as const;

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<typeof TABS[number]["id"]>("ingest");
  const [health, setHealth] = useState<any>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const [form, setForm] = useState({
    source: "email" as "email" | "website" | "messaging",
    sender_name: "John Smith",
    sender_email: "john@acme.com",
    message: "Hi, we are interested in AI automation for our customer support team. We are a company with approximately 200 employees.",
  });
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState<any>(null);

  const [actions, setActions] = useState<any[]>([]);
  const [enquiries, setEnquiries] = useState<any[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [contacts, setContacts] = useState<any[]>([]);

  const pushToast = (message: string, type: Toast["type"] = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3000);
  };

  const fetchHealth = async () => {
    try { setHealth(await getHealth()); } catch {}
  };
  const fetchAll = async () => {
    try {
      const [acts, enqs, logs, crm] = await Promise.all([
        listActions("PENDING_APPROVAL"),
        listEnquiries(),
        listAudit(50),
        listContacts(),
      ]);
      setActions(acts);
      setEnquiries(enqs);
      setAudit(logs);
      setContacts(crm);
    } catch (e: any) { pushToast(e.message, "error"); }
  };

  useEffect(() => {
    fetchHealth();
    fetchAll();
    const iv = setInterval(() => { fetchHealth(); if (activeTab !== "ingest") fetchAll(); }, 8000);
    return () => clearInterval(iv);
  }, [activeTab]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setLastResult(null);
    try {
      const res = await createEnquiry(form);
      setLastResult(res);
      pushToast(`${res.proposed_action?.action_type} · ${Math.round(res.enquiry.ai_confidence * 100)}%`, "success");
      fetchAll();
    } catch (err: any) {
      pushToast(err.message, "error");
    }
    setSubmitting(false);
  };

  const handleApprove = async (id: string) => {
    try { await approveAction(id); pushToast("Approved", "success"); fetchAll(); setLastResult(null); } catch (e: any) { pushToast(e.message, "error"); }
  };
  const handleReject = async (id: string) => {
    try { await rejectAction(id); pushToast("Rejected", "info"); fetchAll(); setLastResult(null); } catch (e: any) { pushToast(e.message, "error"); }
  };

  const presets = [
    { label: "Sales", message: "Hi, we are interested in AI automation for our customer support team. We are a company with approximately 200 employees." },
    { label: "Support", message: "Hello, I can't log in to my account. I get error 500 every time I try to reset my password." },
    { label: "Vague", message: "Hi, I'm interested in your services." },
    { label: "Spam", message: "Congratulations you have won lottery! Claim your crypto giveaway now at http://spam.example" },
  ];

  return (
    <div className="min-h-screen bg-white text-black">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-black/10">
        <div className="max-w-[1120px] mx-auto px-6 h-[56px] flex items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-black text-white flex items-center justify-center rounded-lg">
              <Inbox className="w-4 h-4" />
            </div>
            <span className="font-semibold tracking-tight">InboxOps</span>
            <span className="hidden sm:inline text-xs text-black/40 ml-2">AI suggests · You decide</span>
          </div>

          <nav className="flex items-center gap-6">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`text-sm py-1 border-b-2 transition ${activeTab === t.id ? "border-black font-medium" : "border-transparent text-black/50 hover:text-black"}`}
              >
                {t.label}
                {t.id === "queue" && actions.length > 0 && (
                  <span className="ml-1.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-xs bg-black text-white rounded-full">{actions.length}</span>
                )}
              </button>
            ))}
          </nav>

          <div className="hidden md:flex items-center gap-3 text-xs">
            <a href="http://localhost:8000/docs" target="_blank" className="underline decoration-black/20 hover:decoration-black">API</a>
            <span className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${health?.mock_mode ? "bg-black/30" : "bg-black"}`} />
              {health?.mock_mode ? "Mock" : "Live"}
            </span>
          </div>
        </div>
      </header>

      {/* Subtle principle */}
      <div className="max-w-[1120px] mx-auto px-6">
        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-black/50 border border-black/10 rounded-full w-fit mx-auto px-3 py-1">
          <span className="w-1 h-1 bg-black rounded-full" />
          No automatic sends. Every action needs approval.
        </div>
      </div>

      <main className="max-w-[1120px] mx-auto px-6 py-8">
        {/* INGEST */}
        {activeTab === "ingest" && (
          <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-8">
            {/* Form */}
            <div className="border border-black/10 rounded-2xl p-6">
              <div className="flex items-center gap-2 text-xs text-black/40 uppercase tracking-widest">
                <Sparkles className="w-3 h-3" /> New enquiry
              </div>
              <h1 className="text-xl font-semibold mt-2">Create enquiry</h1>
              <p className="text-sm text-black/50 mt-1">We’ll classify, check duplicates, and prepare a draft. Nothing is sent automatically.</p>

              <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                {/* source */}
                <div className="inline-flex p-1 border border-black/10 rounded-full">
                  {(["email", "website", "messaging"] as const).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, source: s }))}
                      className={`px-4 py-1.5 text-sm rounded-full capitalize ${form.source === s ? "bg-black text-white" : "text-black/60 hover:text-black"}`}
                    >
                      {s}
                    </button>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <label className="space-y-1.5">
                    <span className="text-xs text-black/60">Name</span>
                    <input
                      value={form.sender_name}
                      onChange={(e) => setForm((f) => ({ ...f, sender_name: e.target.value }))}
                      className="w-full h-9 px-3 border border-black/10 rounded-xl text-sm focus:outline-none focus:border-black"
                      required
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className="text-xs text-black/60">Email</span>
                    <input
                      type="email"
                      value={form.sender_email}
                      onChange={(e) => setForm((f) => ({ ...f, sender_email: e.target.value }))}
                      className="w-full h-9 px-3 border border-black/10 rounded-xl text-sm focus:outline-none focus:border-black"
                      required
                    />
                  </label>
                </div>

                <label className="space-y-1.5 block">
                  <span className="text-xs text-black/60">Message</span>
                  <textarea
                    value={form.message}
                    onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
                    rows={5}
                    maxLength={8000}
                    className="w-full p-3 border border-black/10 rounded-xl text-sm resize-none focus:outline-none focus:border-black"
                    placeholder="Paste the raw message…"
                    required
                  />
                  <span className="text-xs text-black/30">{form.message.length} / 8000</span>
                </label>

                <div className="flex flex-wrap gap-1.5">
                  {presets.map((p) => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, message: p.message }))}
                      className="text-xs px-2.5 py-1 border border-black/10 rounded-full hover:bg-black hover:text-white hover:border-black"
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full h-10 bg-black text-white rounded-xl text-sm font-medium inline-flex items-center justify-center gap-2 hover:bg-black/90 disabled:opacity-40"
                >
                  {submitting ? "Processing…" : <>Send to review <ArrowRight className="w-4 h-4" /></>}
                </button>
              </form>
            </div>

            {/* Result */}
            <div className="border border-black/10 rounded-2xl p-6">
              <div className="text-xs text-black/40 uppercase tracking-widest">Result</div>

              {!lastResult ? (
                <div className="mt-8 border border-dashed border-black/10 rounded-xl p-10 text-center">
                  <div className="w-8 h-8 mx-auto rounded-full border border-black/10 flex items-center justify-center">
                    <Inbox className="w-4 h-4 text-black/30" />
                  </div>
                  <div className="text-sm mt-3">No result yet</div>
                  <div className="text-xs text-black/40 mt-1">Submit a message to see the outcome.</div>
                </div>
              ) : (
                <div className="mt-4 space-y-4">
                  <div className="flex flex-wrap gap-2">
                    <span className="px-2.5 py-1 border border-black text-xs rounded-full">{lastResult.enquiry.ai_classification}</span>
                    <span className="px-2.5 py-1 bg-black text-white text-xs rounded-full">{Math.round(lastResult.enquiry.ai_confidence * 100)}%</span>
                    <span className="px-2.5 py-1 border border-black/10 text-xs rounded-full">{lastResult.duplicate_status || "no duplicate"}</span>
                    {lastResult.enquiry.ai_confidence < 0.85 && <span className="px-2.5 py-1 bg-black/5 text-xs rounded-full">needs review</span>}
                  </div>

                  {lastResult.proposed_action && (
                    <div className="border border-black rounded-xl p-4">
                      <div className="text-xs text-black/40 uppercase tracking-widest">Proposed action</div>
                      <div className="font-medium mt-1">{lastResult.proposed_action.action_type}</div>
                      <div className="text-xs text-black/50">Pending approval · Human must confirm</div>

                      {lastResult.proposed_action.draft_response && (
                        <div className="mt-3 bg-black/[0.03] border border-black/5 rounded-xl p-3 text-sm leading-relaxed">
                          “{lastResult.proposed_action.draft_response}”
                        </div>
                      )}

                      <div className="mt-4 grid grid-cols-2 gap-2">
                        <button onClick={() => handleApprove(lastResult.proposed_action.id)} className="h-9 bg-black text-white rounded-xl text-sm inline-flex items-center justify-center gap-1.5">
                          <Check className="w-4 h-4" /> Approve
                        </button>
                        <button onClick={() => handleReject(lastResult.proposed_action.id)} className="h-9 border border-black/10 rounded-xl text-sm inline-flex items-center justify-center gap-1.5 hover:bg-black hover:text-white">
                          <X className="w-4 h-4" /> Reject
                        </button>
                      </div>
                    </div>
                  )}

                  {lastResult.enquiry.ai_output?.missing_information?.length > 0 && (
                    <div className="text-xs text-black/50">Missing: {lastResult.enquiry.ai_output.missing_information.join(" · ")}</div>
                  )}

                  <details className="border border-black/10 rounded-xl">
                    <summary className="px-3 py-2 text-sm cursor-pointer">View JSON</summary>
                    <pre className="mx-3 mb-3 p-3 bg-black/[0.03] rounded-xl text-xs overflow-auto max-h-52">{JSON.stringify(lastResult.enquiry.ai_output, null, 2)}</pre>
                  </details>
                </div>
              )}
            </div>
          </div>
        )}

        {/* QUEUE */}
        {activeTab === "queue" && (
          <div>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Queue <span className="text-black/40 font-normal">· {actions.length}</span></h2>
              <button onClick={fetchAll} className="text-xs underline">Refresh</button>
            </div>

            {actions.length === 0 ? (
              <div className="mt-6 border border-dashed border-black/10 rounded-2xl p-12 text-center">
                <Clock className="w-5 h-5 mx-auto text-black/20" />
                <div className="text-sm mt-2">All clear</div>
                <div className="text-xs text-black/40">No pending approvals</div>
              </div>
            ) : (
              <div className="mt-6 space-y-3">
                {actions.map((a) => (
                  <div key={a.id} className="border border-black/10 rounded-2xl p-4 flex gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap gap-1.5">
                        <span className="px-2 py-1 bg-black text-white text-xs rounded-full">{a.action_type}</span>
                        {a.duplicate_status && a.duplicate_status !== "none" && <span className="px-2 py-1 border border-black/10 text-xs rounded-full">{a.duplicate_status}</span>}
                        {a.confidence != null && <span className="px-2 py-1 border border-black/10 text-xs rounded-full">{Math.round(a.confidence * 100)}%</span>}
                      </div>
                      <div className="text-sm mt-2 line-clamp-2">{a.enquiry?.message}</div>
                      <div className="text-xs text-black/50 mt-1">{a.enquiry?.sender_name} · {a.enquiry?.sender_email}</div>
                      {a.draft_response && <div className="text-sm mt-2 italic text-black/70">“{a.draft_response}”</div>}
                    </div>
                    <div className="flex flex-col gap-2">
                      <button onClick={() => handleApprove(a.id)} className="h-8 px-4 bg-black text-white rounded-full text-xs inline-flex items-center gap-1"><Check className="w-3 h-3" /> Approve</button>
                      <button onClick={() => handleReject(a.id)} className="h-8 px-4 border border-black/10 rounded-full text-xs inline-flex items-center gap-1"><X className="w-3 h-3" /> Reject</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* HISTORY */}
        {activeTab === "enquiries" && (
          <div>
            <h2 className="font-semibold">History <span className="text-black/40 font-normal">· {enquiries.length}</span></h2>
            <div className="mt-4 border border-black/10 rounded-2xl overflow-hidden">
              <div className="overflow-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-black/40 border-b border-black/10">
                    <tr><th className="text-left font-normal px-4 py-2">From</th><th className="text-left font-normal px-4 py-2">Type</th><th className="text-left font-normal px-4 py-2">Message</th><th className="text-left font-normal px-4 py-2">Status</th></tr>
                  </thead>
                  <tbody className="divide-y divide-black/5">
                    {enquiries.map((e) => (
                      <tr key={e.id}>
                        <td className="px-4 py-2"><div className="font-medium">{e.sender_name}</div><div className="text-xs text-black/40">{e.sender_email}</div></td>
                        <td className="px-4 py-2 text-xs">{e.ai_classification || "—"} · {e.ai_confidence ? Math.round(e.ai_confidence * 100) + "%" : ""}</td>
                        <td className="px-4 py-2 max-w-[320px] truncate text-black/60">{e.message}</td>
                        <td className="px-4 py-2 text-xs">{e.processing_status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {enquiries.length === 0 && <div className="p-8 text-center text-sm text-black/40">Empty</div>}
              </div>
            </div>
          </div>
        )}

        {/* LOG */}
        {activeTab === "audit" && (
          <div>
            <h2 className="font-semibold">Log</h2>
            <div className="mt-4 border border-black/10 rounded-2xl p-3">
              <div className="space-y-1 max-h-[520px] overflow-auto pr-1">
                {audit.map((l: any) => (
                  <div key={l.id} className="flex gap-3 py-2 border-b border-black/5 last:border-0">
                    <span className="text-xs font-mono mt-0.5">{l.event_type}</span>
                    <span className="text-xs text-black/40">{l.entity_type} · {l.entity_id.slice(0, 6)}</span>
                    <span className="text-xs text-black/30 ml-auto">{new Date(l.created_at).toLocaleString()}</span>
                  </div>
                ))}
                {audit.length === 0 && <div className="text-sm text-black/40 text-center py-8">No events</div>}
              </div>
            </div>
          </div>
        )}

        {/* CONTACTS */}
        {activeTab === "crm" && (
          <div>
            <h2 className="font-semibold">Contacts <span className="text-black/40 font-normal">· {contacts.length}</span></h2>
            <div className="mt-4 grid gap-3">
              {contacts.map((c: any) => (
                <div key={c.id} className="border border-black/10 rounded-2xl p-4 flex justify-between">
                  <div>
                    <div className="font-medium text-sm">{c.name || "—"}</div>
                    <div className="text-xs text-black/50">{c.email} {c.phone ? "· " + c.phone : ""}</div>
                    {c.company && <div className="text-xs text-black/70 mt-1">{c.company.name}</div>}
                  </div>
                  <div className="text-xs text-black/30 font-mono">{c.id.slice(0, 6)}</div>
                </div>
              ))}
              {contacts.length === 0 && <div className="border border-dashed border-black/10 rounded-2xl p-10 text-center text-sm text-black/40">Approve a lead to create a contact</div>}
            </div>
          </div>
        )}
      </main>

      <footer className="max-w-[1120px] mx-auto px-6 py-6 border-t border-black/10 mt-8">
        <div className="text-xs text-black/40 text-center">InboxOps · Minimal · Human decides · <a href="http://localhost:8000/docs" target="_blank" className="underline">API</a></div>
      </footer>

      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 space-y-2">
        {toasts.map((t) => (
          <div key={t.id} className="px-3 py-2 bg-black text-white rounded-full text-sm shadow-lg">{t.message}</div>
        ))}
      </div>
    </div>
  );
}
