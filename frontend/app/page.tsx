"use client";

import { useEffect, useState } from "react";
import { createEnquiry, listActions, approveAction, rejectAction, getHealth, listEnquiries, listAudit, listContacts, getInsightsSummary, getInsightsRecent, getEnquiryInsight, deleteEnquiry, deleteContact } from "@/lib/api";
import { Inbox, Check, X, Clock, ArrowRight, Sparkles, Eye, Filter, TrendingUp, Trash2 } from "lucide-react";

type Toast = { id: string; message: string; type: "success" | "error" | "info" };

const TABS = [
  { id: "ingest", label: "New" },
  { id: "queue", label: "Queue" },
  { id: "insights", label: "Insights" },
  { id: "enquiries", label: "History" },
  { id: "audit", label: "Log" },
  { id: "crm", label: "Customers" },
] as const;

// Layperson-friendly labels — no underscores, full words
const TEAM_LABELS: Record<string, string> = {
  sales: "Sales",
  support: "Support",
  billing_finance: "Billing and Finance",
  partnership: "Partnership",
  operations: "Operations",
  marketing: "Marketing",
  hr: "Human Resources",
  legal: "Legal",
  triage: "General Support",
};
const ACTION_LABELS: Record<string, string> = {
  CREATE_LEAD: "Create New Customer",
  UPDATE_CONTACT: "Update Customer",
  CREATE_SUPPORT_CASE: "Create Support Ticket",
  REQUEST_MORE_INFORMATION: "Ask for More Details",
  MARK_AS_JUNK: "Mark as Spam",
};
const CLASS_LABELS: Record<string, string> = {
  sales: "Sales Opportunity",
  support: "Support Request",
  junk: "Spam",
  insufficient_information: "Needs More Info",
  other: "Other",
};
const SOURCE_LABELS: Record<string, string> = {
  email: "Email",
  website: "Website Form",
  messaging: "Chat Message",
};
const PRIORITY_LABELS: Record<string, string> = {
  low: "Low Priority",
  medium: "Medium Priority",
  high: "High Priority",
};
function labelTeam(v?: string) { if (!v) return "—"; return TEAM_LABELS[v] || v.replace(/_/g, " "); }
function labelAction(v?: string) { if (!v) return "—"; return ACTION_LABELS[v] || v.replace(/_/g, " "); }
function labelClass(v?: string) { if (!v) return "—"; return CLASS_LABELS[v] || v.replace(/_/g, " "); }
function labelSource(v?: string) { if (!v) return "—"; return SOURCE_LABELS[v] || v; }
function labelPriority(v?: string) { if (!v) return ""; return PRIORITY_LABELS[v] || v; }
function displayEmail(email?: string) { if (!email || email.endsWith("@chat.local")) return "via Chat"; return email; }

function InsightPanel({ data, compact = false }: { data: any; compact?: boolean }) {
  if (!data) return null;
  const out = data.ai_output || data.insight || data;
  const meta = data.metadata || out || {};
  const keywords = out.intent_keywords || meta.intent_keywords || [];
  const priority = out.priority || meta.priority;
  const team = out.suggested_team || meta.suggested_team;
  const owner = meta.assigned_owner;
  const intent = out.intent || meta.intent;
  const missing = out.missing_information || meta.missing_information || [];
  const confidence = data.ai_confidence ?? out.confidence ?? data.confidence;
  const source = data.source || out.source || meta.source;
  return (
    <div className={`border border-black/10 rounded-xl p-3 space-y-2 ${compact ? "text-xs" : "text-sm"}`}>
      <div className="flex flex-wrap gap-1.5">
        {source && <span className="px-2 py-1 bg-black/5 border border-black/10 text-xs rounded-full">{labelSource(source)}</span>}
        {team && <span className="px-2 py-1 bg-black text-white text-xs rounded-full">{labelTeam(team)}</span>}
        {priority && <span className={`px-2 py-1 text-xs rounded-full ${priority === "high" ? "bg-black text-white" : priority === "medium" ? "border border-black" : "bg-black/5 border border-black/10"}`}>{labelPriority(priority)}</span>}
        {confidence != null && <span className="px-2 py-1 border border-black/10 text-xs rounded-full">Confidence {Math.round(confidence * 100)}%</span>}
        {owner && <span className="px-2 py-1 border border-black/10 text-xs rounded-full text-black/60">Person in Charge: {owner}</span>}
      </div>
      {intent && <div className="text-sm text-black/80"><span className="text-black/40">Customer Need:</span> {intent}</div>}
      {keywords?.length > 0 && <div className="flex flex-wrap gap-1"><span className="text-xs text-black/40">Key Topics:</span>{keywords.map((k: string) => <span key={k} className="px-1.5 py-0.5 bg-black/[0.03] border border-black/5 rounded-full text-xs">{k}</span>)}</div>}
      {missing?.length > 0 && <div className="text-xs text-black/50">Still Needs: {missing.join(" · ")}</div>}
    </div>
  );
}

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
  const [insightsSummary, setInsightsSummary] = useState<any>(null);
  const [insightsRecent, setInsightsRecent] = useState<any[]>([]);
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const [selectedInsight, setSelectedInsight] = useState<any>(null);
  const [insightLoading, setInsightLoading] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<{ type: "insight" | "customer"; id: string; label: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

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
  const fetchInsights = async () => {
    try {
      const [summary, recent] = await Promise.all([
        getInsightsSummary(),
        getInsightsRecent({ limit: "12", ...(sourceFilter !== "all" ? { source: sourceFilter } : {}), ...(teamFilter !== "all" ? { team: teamFilter } : {}) }),
      ]);
      setInsightsSummary(summary);
      setInsightsRecent(recent);
    } catch (e: any) { /* ignore */ }
  };

  useEffect(() => {
    fetchHealth();
    fetchAll();
    fetchInsights();
    const iv = setInterval(() => { fetchHealth(); fetchInsights(); if (activeTab !== "ingest") fetchAll(); }, 8000);
    return () => clearInterval(iv);
  }, [activeTab, sourceFilter, teamFilter]);

  const isChat = form.source === "messaging";
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // chat: email not required, omit if empty
    if (!isChat && !form.sender_email?.trim()) {
      pushToast("Customer Email is required for Email and Website Form", "error");
      return;
    }
    if (!isChat && form.sender_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.sender_email)) {
      pushToast("Please enter a valid email", "error");
      return;
    }
    setSubmitting(true);
    setLastResult(null);
    try {
      const payload: any = {
        source: form.source,
        sender_name: form.sender_name,
        message: form.message,
      };
      if (!isChat) payload.sender_email = form.sender_email;
      // for chat, only send email if user explicitly filled it
      else if (form.sender_email?.trim()) payload.sender_email = form.sender_email.trim();
      const res = await createEnquiry(payload);
      setLastResult(res);
      pushToast(`${labelTeam(res.proposed_action?.metadata?.suggested_team) || labelClass(res.enquiry.ai_classification)} · ${Math.round(res.enquiry.ai_confidence * 100)}% via ${labelSource(form.source)}`, "success");
      fetchAll(); fetchInsights();
    } catch (err: any) {
      pushToast(err.message, "error");
    }
    setSubmitting(false);
  };

  const handleApprove = async (id: string) => {
    try { await approveAction(id); pushToast("Approved", "success"); fetchAll(); fetchInsights(); setSelectedInsight(null); setLastResult(null); } catch (e: any) { pushToast(e.message, "error"); }
  };
  const handleReject = async (id: string) => {
    try { await rejectAction(id); pushToast("Rejected", "info"); fetchAll(); fetchInsights(); setSelectedInsight(null); setLastResult(null); } catch (e: any) { pushToast(e.message, "error"); }
  };
  const openInsight = async (enquiryId: string) => {
    setInsightLoading(true);
    try { const data = await getEnquiryInsight(enquiryId); setSelectedInsight(data); } catch (e: any) { pushToast(e.message, "error"); }
    setInsightLoading(false);
  };

  const handleDeleteInsight = async (enquiryId: string) => {
    setDeleting(true);
    try { await deleteEnquiry(enquiryId); pushToast("Insight deleted", "success"); setSelectedInsight(null); fetchAll(); fetchInsights(); } catch (e: any) { pushToast(e.message, "error"); }
    setDeleting(false); setConfirmDelete(null);
  };
  const handleDeleteCustomer = async (contactId: string) => {
    setDeleting(true);
    try { await deleteContact(contactId); pushToast("Customer deleted", "success"); fetchAll(); } catch (e: any) { pushToast(e.message, "error"); }
    setDeleting(false); setConfirmDelete(null);
  };

  const filteredActions = actions.filter(a => sourceFilter === "all" || a.enquiry?.source === sourceFilter).filter(a => teamFilter === "all" || a.metadata?.suggested_team === teamFilter);
  const filteredEnquiries = enquiries.filter(e => sourceFilter === "all" || e.source === sourceFilter);

  return (
    <div className="min-h-screen bg-white text-black">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-black/10">
        <div className="max-w-[1220px] mx-auto px-6 h-[56px] flex items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-black text-white flex items-center justify-center rounded-lg">
              <Inbox className="w-4 h-4" />
            </div>
            <span className="font-semibold tracking-tight">InboxOps</span>
            <span className="hidden sm:inline text-xs text-black/40 ml-2">Smart help · You decide</span>
          </div>

          <nav className="flex items-center gap-4">
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
                {t.id === "insights" && insightsSummary && (
                  <span className="ml-1.5 text-xs text-black/30">{insightsSummary.total_enquiries}</span>
                )}
              </button>
            ))}
          </nav>

          <div className="hidden md:flex items-center gap-3 text-xs">
            <a href="http://localhost:8000/docs" target="_blank" className="underline decoration-black/20 hover:decoration-black">Developer Docs</a>
            <span className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${health?.mock_mode ? "bg-black/30" : "bg-black"}`} />
              {health?.mock_mode ? "Demo Mode" : "Live Connected"}
            </span>
          </div>
        </div>
      </header>

      {/* Principle + source hint */}
      <div className="max-w-[1220px] mx-auto px-6">
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2 text-xs text-black/50">
          <span className="border border-black/10 rounded-full px-3 py-1 flex items-center gap-2"><span className="w-1 h-1 bg-black rounded-full" /> No message is sent automatically. Every action needs your approval.</span>
          <span className="border border-black/10 rounded-full px-3 py-1">How you contacted us helps us route better · Email is formal · Website form is often a new opportunity · Chat is often urgent</span>
        </div>
      </div>

      <main className="max-w-[1220px] mx-auto px-6 py-8">
        {/* Global filters for insights/history/queue */}
        {(activeTab === "insights" || activeTab === "enquiries" || activeTab === "queue") && (
          <div className="mb-6 flex flex-wrap items-center gap-2">
            <span className="text-xs text-black/40 flex items-center gap-1"><Filter className="w-3 h-3" /> Filter by:</span>
            <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)} className="h-7 px-2 border border-black/10 rounded-full text-xs bg-white">
              <option value="all">All Channels</option>
              <option value="email">Email</option>
              <option value="website">Website Form</option>
              <option value="messaging">Chat Message</option>
            </select>
            <select value={teamFilter} onChange={e => setTeamFilter(e.target.value)} className="h-7 px-2 border border-black/10 rounded-full text-xs bg-white">
              <option value="all">All Teams</option>
              <option value="sales">Sales</option>
              <option value="support">Support</option>
              <option value="billing_finance">Billing and Finance</option>
              <option value="partnership">Partnership</option>
              <option value="operations">Operations</option>
              <option value="marketing">Marketing</option>
              <option value="hr">Human Resources</option>
              <option value="legal">Legal</option>
              <option value="triage">General Support</option>
            </select>
            {(sourceFilter !== "all" || teamFilter !== "all") && <button onClick={() => { setSourceFilter("all"); setTeamFilter("all"); }} className="text-xs underline">Clear Filters</button>}
          </div>
        )}

        {/* INGEST */}
        {activeTab === "ingest" && (
          <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-8">
            {/* Form */}
            <div className="border border-black/10 rounded-2xl p-6">
              <div className="flex items-center gap-2 text-xs text-black/40 uppercase tracking-widest">
                <Sparkles className="w-3 h-3" /> New Message
              </div>
              <h1 className="text-xl font-semibold mt-2">Create a new enquiry</h1>
              <p className="text-sm text-black/50 mt-1">We will understand the message, find key topics, choose the right team, and prepare a reply draft. Nothing is sent without your approval.</p>

              <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                {/* source — 2 lines: question on line 1, choices on line 2 */}
                <div className="space-y-2">
                  <div className="text-xs text-black/60">How did the customer contact you?</div>
                  <div className="inline-flex p-1 border border-black/10 rounded-full">
                    {(["email", "website", "messaging"] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setForm((f) => ({ ...f, source: s }))}
                        className={`px-4 py-1.5 text-sm rounded-full ${form.source === s ? "bg-black text-white" : "text-black/60 hover:text-black"}`}
                      >
                        {labelSource(s)}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="text-xs text-black/40">
                  {form.source === "email" && "Email is treated as formal business correspondence"}
                  {form.source === "website" && "Website form is often a new opportunity and tends to go to Sales or Marketing"}
                  {form.source === "messaging" && "Chat messages are often short and urgent and tend to go to Support"}
                </div>

                {isChat ? (
                  <label className="space-y-1.5">
                    <span className="text-xs text-black/60">Customer Name / Handle</span>
                    <input
                      value={form.sender_name}
                      onChange={(e) => setForm((f) => ({ ...f, sender_name: e.target.value }))}
                      className="w-full h-9 px-3 border border-black/10 rounded-xl text-sm focus:outline-none focus:border-black"
                      placeholder="e.g. john_doe"
                      required
                    />
                    <span className="text-xs text-black/30">Chat does not require email — leave blank if not available</span>
                  </label>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    <label className="space-y-1.5">
                      <span className="text-xs text-black/60">Customer Name</span>
                      <input
                        value={form.sender_name}
                        onChange={(e) => setForm((f) => ({ ...f, sender_name: e.target.value }))}
                        className="w-full h-9 px-3 border border-black/10 rounded-xl text-sm focus:outline-none focus:border-black"
                        required
                      />
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs text-black/60">Customer Email</span>
                      <input
                        type="email"
                        value={form.sender_email}
                        onChange={(e) => setForm((f) => ({ ...f, sender_email: e.target.value }))}
                        className="w-full h-9 px-3 border border-black/10 rounded-xl text-sm focus:outline-none focus:border-black"
                        placeholder="name@company.com"
                        required={!isChat}
                      />
                    </label>
                  </div>
                )}

                <label className="space-y-1.5 block">
                  <span className="text-xs text-black/60">Message from Customer</span>
                  <textarea
                    value={form.message}
                    onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
                    rows={5}
                    maxLength={2000}
                    className="w-full p-3 border border-black/10 rounded-xl text-sm resize-none focus:outline-none focus:border-black"
                    placeholder="Paste the original message here…"
                    required
                  />
                  <span className="text-xs text-black/30">{form.message.length} / 2000</span>
                </label>

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full h-10 bg-black text-white rounded-xl text-sm font-medium inline-flex items-center justify-center gap-2 hover:bg-black/90 disabled:opacity-40"
                >
                  {submitting ? "Checking…" : <>Send for Review <ArrowRight className="w-4 h-4" /></>}
                </button>
              </form>
            </div>

            {/* Result + Insight */}
            <div className="border border-black/10 rounded-2xl p-6">
              <div className="text-xs text-black/40 uppercase tracking-widest">Smart Analysis</div>

              {!lastResult ? (
                <div className="mt-8 border border-dashed border-black/10 rounded-xl p-10 text-center">
                  <div className="w-8 h-8 mx-auto rounded-full border border-black/10 flex items-center justify-center">
                    <Inbox className="w-4 h-4 text-black/30" />
                  </div>
                  <div className="text-sm mt-3">No analysis yet</div>
                  <div className="text-xs text-black/40 mt-1">Submit a message to see what the AI understood, the key topics, the responsible team and the draft reply.</div>
                  <div className="text-xs text-black/30 mt-3">Tip: try the same message with a different channel to see how the suggested team changes.</div>
                </div>
              ) : (
                <div className="mt-4 space-y-4">
                  <div className="flex flex-wrap gap-2">
                    <span className="px-2.5 py-1 border border-black text-xs rounded-full">{labelClass(lastResult.enquiry.ai_classification)}</span>
                    <span className="px-2.5 py-1 bg-black text-white text-xs rounded-full">Confidence {Math.round(lastResult.enquiry.ai_confidence * 100)}%</span>
                    <span className="px-2.5 py-1 border border-black/10 text-xs rounded-full">{labelSource(lastResult.enquiry.source)}</span>
                    <span className="px-2.5 py-1 border border-black/10 text-xs rounded-full">{lastResult.duplicate_status && lastResult.duplicate_status !== "none" ? "Possible Duplicate" : "No Duplicate"}</span>
                    {lastResult.enquiry.ai_confidence < 0.85 && <span className="px-2.5 py-1 bg-black/5 text-xs rounded-full">Needs Human Review</span>}
                  </div>

                  {/* Insight Panel */}
                  <InsightPanel data={{ ai_output: lastResult.enquiry.ai_output, metadata: lastResult.proposed_action?.metadata, source: lastResult.enquiry.source, ai_confidence: lastResult.enquiry.ai_confidence }} />

                  {lastResult.proposed_action && (
                    <div className="border border-black rounded-xl p-4">
                      <div className="text-xs text-black/40 uppercase tracking-widest">Suggested Next Step</div>
                      <div className="font-medium mt-1">{labelAction(lastResult.proposed_action.action_type)}</div>
                      <div className="text-xs text-black/50">Responsible Team: {labelTeam(lastResult.proposed_action.metadata?.suggested_team)} · Person in Charge: {lastResult.proposed_action.metadata?.assigned_owner} · Waiting for your approval · Nothing sent yet</div>

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

                  <details className="border border-black/10 rounded-xl">
                    <summary className="px-3 py-2 text-sm cursor-pointer">Show technical details</summary>
                    <pre className="mx-3 mb-3 p-3 bg-black/[0.03] rounded-xl text-xs overflow-auto max-h-52">{JSON.stringify(lastResult.enquiry.ai_output, null, 2)}</pre>
                  </details>
                </div>
              )}
            </div>
          </div>
        )}

        {/* INSIGHTS DASHBOARD */}
        {activeTab === "insights" && (
          <div className="space-y-6">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5" />
              <h2 className="font-semibold">Analysis Overview</h2>
              <span className="text-black/40 text-sm">· stays visible even after you approve or reject</span>
              <button onClick={fetchInsights} className="ml-auto text-xs underline">Refresh</button>
            </div>

            {!insightsSummary ? (
              <div className="border border-dashed border-black/10 rounded-2xl p-10 text-center text-sm text-black/40">Loading overview…</div>
            ) : (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  <div className="border border-black/10 rounded-2xl p-4">
                    <div className="text-xs text-black/40 uppercase">Total Messages</div>
                    <div className="text-2xl font-semibold mt-1">{insightsSummary.total_enquiries}</div>
                    <div className="text-xs text-black/40">{insightsSummary.total_actions} suggested next steps</div>
                  </div>
                  <div className="border border-black/10 rounded-2xl p-4">
                    <div className="text-xs text-black/40 uppercase">By Channel</div>
                    <div className="mt-2 space-y-1 text-xs">{Object.entries(insightsSummary.by_source || {}).map(([k, v]: any) => <div key={k} className="flex justify-between"><span>{labelSource(k)}</span><span className="font-mono">{String(v)}</span></div>)}</div>
                  </div>
                  <div className="border border-black/10 rounded-2xl p-4">
                    <div className="text-xs text-black/40 uppercase">By Responsible Team</div>
                    <div className="mt-2 space-y-1 text-xs">{Object.entries(insightsSummary.by_team || {}).map(([k, v]: any) => <div key={k} className="flex justify-between"><span>{labelTeam(k)}</span><span className="font-mono">{String(v)}</span></div>)}</div>
                  </div>
                  <div className="border border-black/10 rounded-2xl p-4">
                    <div className="text-xs text-black/40 uppercase">By Priority Level</div>
                    <div className="mt-2 space-y-1 text-xs">{Object.entries(insightsSummary.by_priority || {}).map(([k, v]: any) => <div key={k} className="flex justify-between"><span>{labelPriority(k)}</span><span className="font-mono">{String(v)}</span></div>)}</div>
                  </div>
                </div>

                <div className="grid lg:grid-cols-2 gap-3">
                  <div className="border border-black/10 rounded-2xl p-4">
                    <div className="text-xs text-black/40 uppercase">By Category</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(insightsSummary.by_classification || {}).map(([k, v]: any) => <span key={k} className="px-2 py-1 border border-black/10 rounded-full text-xs">{labelClass(k)} · {String(v)}</span>)}</div>
                  </div>
                  <div className="border border-black/10 rounded-2xl p-4">
                    <div className="text-xs text-black/40 uppercase">Most Often Missing</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(insightsSummary.top_missing_information || {}).map(([k, v]: any) => <span key={k} className="px-2 py-1 bg-black/5 border border-black/10 rounded-full text-xs">{k} · {String(v)}</span>)}</div>
                  </div>
                </div>

                {/* Recent insights */}
                <div>
                  <h3 className="font-medium text-sm">Recent Messages — Tap the eye to see the full analysis (still there after review)</h3>
                  <div className="mt-3 grid gap-3">
                    {insightsRecent.map((item: any) => (
                      <div key={item.enquiry.id} className="border border-black/10 rounded-2xl p-4">
                        <div className="flex gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex flex-wrap gap-1.5 items-center">
                              <span className="px-2 py-1 bg-black text-white text-xs rounded-full">{labelSource(item.enquiry.source)}</span>
                              <span className="px-2 py-1 border border-black text-xs rounded-full">{labelClass(item.enquiry.ai_classification)}</span>
                              <span className="px-2 py-1 border border-black/10 text-xs rounded-full">{labelTeam(item.insight.suggested_team)}</span>
                              {item.insight.priority && <span className="px-2 py-1 border border-black/10 text-xs rounded-full">{labelPriority(item.insight.priority)}</span>}
                              <span className="text-xs text-black/30 ml-1">{new Date(item.enquiry.created_at).toLocaleString()}</span>
                            </div>
                            <div className="text-sm mt-2 line-clamp-2">{item.enquiry.message}</div>
                            <div className="text-xs text-black/50 mt-1">{item.enquiry.sender_name} · {displayEmail(item.enquiry.sender_email)}</div>
                            <div className="mt-2"><InsightPanel data={item} compact /></div>
                            {item.action?.draft_response && <div className="text-xs mt-2 italic text-black/60">“{item.action.draft_response}”</div>}
                          </div>
                          <div className="flex flex-col gap-2">
                            <button onClick={() => openInsight(item.enquiry.id)} className="h-8 px-3 border border-black/10 rounded-full text-xs inline-flex items-center gap-1 hover:bg-black hover:text-white"><Eye className="w-3 h-3" /> View Analysis</button>
                            <button onClick={() => setConfirmDelete({ type: "insight", id: item.enquiry.id, label: displayEmail(item.enquiry.sender_email) })} className="h-8 px-3 border border-black/10 rounded-full text-xs inline-flex items-center gap-1 hover:bg-black hover:text-white text-black/60 hover:text-white"><Trash2 className="w-3 h-3" /> Delete</button>
                            <span className={`h-6 px-2 rounded-full text-xs inline-flex items-center justify-center ${item.action?.status === "EXECUTED" ? "bg-black text-white" : item.action?.status === "PENDING_APPROVAL" ? "border border-black/10" : "bg-black/5"}`}>{item.action?.status === "EXECUTED" ? "Approved and Done" : item.action?.status === "PENDING_APPROVAL" ? "Waiting for Review" : (item.action?.status || "—").replace(/_/g, " ")}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                    {insightsRecent.length === 0 && <div className="text-sm text-black/40 text-center py-8">No messages yet — create one on the New tab with different channels (Email, Website Form, Chat) to see how the suggested team changes</div>}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* QUEUE */}
        {activeTab === "queue" && (
          <div>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Waiting for Review <span className="text-black/40 font-normal">· {filteredActions.length} of {actions.length}</span></h2>
              <button onClick={fetchAll} className="text-xs underline">Refresh</button>
            </div>

            {filteredActions.length === 0 ? (
              <div className="mt-6 border border-dashed border-black/10 rounded-2xl p-12 text-center">
                <Clock className="w-5 h-5 mx-auto text-black/20" />
                <div className="text-sm mt-2">All caught up</div>
                <div className="text-xs text-black/40">No items waiting {sourceFilter !== "all" || teamFilter !== "all" ? "for this filter" : ""}</div>
              </div>
            ) : (
              <div className="mt-6 space-y-3">
                {filteredActions.map((a) => (
                  <div key={a.id} className="border border-black/10 rounded-2xl p-4 flex gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap gap-1.5">
                        <span className="px-2 py-1 bg-black text-white text-xs rounded-full">{labelAction(a.action_type)}</span>
                        <span className="px-2 py-1 border border-black/10 text-xs rounded-full">{labelSource(a.enquiry?.source)}</span>
                        {a.metadata?.suggested_team && <span className="px-2 py-1 bg-black/5 border border-black/10 text-xs rounded-full">{labelTeam(a.metadata.suggested_team)}</span>}
                        {a.metadata?.priority && <span className={`px-2 py-1 text-xs rounded-full ${a.metadata.priority === "high" ? "bg-black text-white" : "border border-black/10"}`}>{labelPriority(a.metadata.priority)}</span>}
                        {a.duplicate_status && a.duplicate_status !== "none" && <span className="px-2 py-1 border border-black/10 text-xs rounded-full">Possible Duplicate</span>}
                        {a.confidence != null && <span className="px-2 py-1 border border-black/10 text-xs rounded-full">Confidence {Math.round(a.confidence * 100)}%</span>}
                      </div>
                      <div className="text-sm mt-2 line-clamp-2">{a.enquiry?.message}</div>
                      <div className="text-xs text-black/50 mt-1">{a.enquiry?.sender_name} · {displayEmail(a.enquiry?.sender_email)} · Person in Charge: {a.metadata?.assigned_owner}</div>
                      <div className="mt-2 flex flex-wrap gap-1">{(a.metadata?.intent_keywords || []).map((k: string) => <span key={k} className="px-1.5 py-0.5 bg-black/[0.03] border border-black/5 rounded-full text-xs">{k}</span>)}</div>
                      {a.draft_response && <div className="text-sm mt-2 italic text-black/70">“{a.draft_response}”</div>}
                      <button onClick={() => a.enquiry && openInsight(a.enquiry.id)} className="text-xs underline mt-2 inline-flex items-center gap-1"><Eye className="w-3 h-3" /> View Full Analysis</button>
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
            <h2 className="font-semibold">Past Messages <span className="text-black/40 font-normal">· {filteredEnquiries.length} of {enquiries.length}</span></h2>
            <div className="mt-4 border border-black/10 rounded-2xl overflow-hidden">
              <div className="overflow-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-black/40 border-b border-black/10">
                    <tr><th className="text-left font-normal px-4 py-2">Customer</th><th className="text-left font-normal px-4 py-2">Channel</th><th className="text-left font-normal px-4 py-2">Category</th><th className="text-left font-normal px-4 py-2">Responsible Team</th><th className="text-left font-normal px-4 py-2">Key Topics</th><th className="text-left font-normal px-4 py-2">Status</th></tr>
                  </thead>
                  <tbody className="divide-y divide-black/5">
                    {filteredEnquiries.map((e) => (
                      <tr key={e.id} className="hover:bg-black/[0.02] cursor-pointer" onClick={() => openInsight(e.id)}>
                        <td className="px-4 py-2"><div className="font-medium">{e.sender_name}</div><div className="text-xs text-black/40">{displayEmail(e.sender_email)}</div></td>
                        <td className="px-4 py-2 text-xs">{labelSource(e.source)}</td>
                        <td className="px-4 py-2 text-xs">{labelClass(e.ai_classification)} · {e.ai_confidence ? Math.round(e.ai_confidence * 100) + "%" : ""}</td>
                        <td className="px-4 py-2 text-xs">{labelTeam(e.ai_output?.suggested_team)}</td>
                        <td className="px-4 py-2 text-xs max-w-[220px] truncate text-black/50 flex items-center gap-1"><Eye className="w-3 h-3" /> {(e.ai_output?.intent_keywords || []).join(", ") || e.ai_output?.intent || "—"}</td>
                        <td className="px-4 py-2 text-xs">{e.processing_status === "COMPLETED" ? "Done" : e.processing_status === "FAILED" ? "Needs Attention" : e.processing_status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {filteredEnquiries.length === 0 && <div className="p-8 text-center text-sm text-black/40">Nothing for this filter</div>}
              </div>
            </div>
            <div className="text-xs text-black/30 mt-2">Tap a row to see the full AI analysis — it stays available even after you approve or reject.</div>
          </div>
        )}

        {/* LOG */}
        {activeTab === "audit" && (
          <div>
            <h2 className="font-semibold">Activity Log</h2>
            <div className="mt-4 border border-black/10 rounded-2xl p-3">
              <div className="space-y-1 max-h-[520px] overflow-auto pr-1">
                {audit.map((l: any) => (
                  <div key={l.id} className="flex gap-3 py-2 border-b border-black/5 last:border-0">
                    <span className="text-xs font-mono mt-0.5">{l.event_type.replace(/_/g, " ")}</span>
                    <span className="text-xs text-black/40">{l.entity_type} · {l.entity_id.slice(0, 6)} {l.metadata?.suggested_team ? `· ${labelTeam(l.metadata.suggested_team)}` : ""} {l.metadata?.assigned_owner ? `· ${l.metadata.assigned_owner}` : ""}</span>
                    <span className="text-xs text-black/30 ml-auto">{new Date(l.created_at).toLocaleString()}</span>
                  </div>
                ))}
                {audit.length === 0 && <div className="text-sm text-black/40 text-center py-8">No activity yet</div>}
              </div>
            </div>
          </div>
        )}

        {/* CUSTOMERS */}
        {activeTab === "crm" && (
          <div>
            <h2 className="font-semibold">Customers <span className="text-black/40 font-normal">· {contacts.length}</span></h2>
            <div className="mt-4 grid gap-3">
              {contacts.map((c: any) => (
                <div key={c.id} className="border border-black/10 rounded-2xl p-4 flex justify-between items-center">
                  <div>
                    <div className="font-medium text-sm">{c.name || "—"}</div>
                    <div className="text-xs text-black/50">{c.email} {c.phone ? "· " + c.phone : ""}</div>
                    {c.company && <div className="text-xs text-black/70 mt-1">{c.company.name}</div>}
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-xs text-black/30 font-mono">{c.id.slice(0, 6)}</div>
                    <button onClick={() => setConfirmDelete({ type: "customer", id: c.id, label: c.email || c.name })} className="h-8 px-3 border border-black/10 rounded-full text-xs inline-flex items-center gap-1 hover:bg-black hover:text-white"><Trash2 className="w-3 h-3" /> Delete</button>
                  </div>
                </div>
              ))}
              {contacts.length === 0 && <div className="border border-dashed border-black/10 rounded-2xl p-10 text-center text-sm text-black/40">No customers yet — approve a suggested next step to create one</div>}
            </div>
          </div>
        )}

        {/* Analysis modal — layperson, no underscores */}
        {selectedInsight && (
          <div className="fixed inset-0 z-40 flex items-center justify-center p-4 bg-black/30" onClick={() => setSelectedInsight(null)}>
            <div className="bg-white rounded-2xl max-w-[800px] w-full max-h-[85vh] overflow-auto p-6" onClick={e => e.stopPropagation()}>
              <div className="flex items-start justify-between gap-4">
                <h3 className="font-semibold">What the AI Understood — still available after review</h3>
                <button onClick={() => setSelectedInsight(null)} className="h-7 w-7 border border-black/10 rounded-full flex items-center justify-center"><X className="w-4 h-4" /></button>
              </div>
              {insightLoading ? <div className="text-sm text-black/40 mt-4">Loading…</div> : (
                <div className="mt-4 space-y-4">
                  <div className="border border-black/10 rounded-xl p-3 text-sm">
                    <div className="text-xs text-black/40 uppercase">Original Message ({labelSource(selectedInsight.enquiry.source)})</div>
                    <div className="mt-1">{selectedInsight.enquiry.message}</div>
                    <div className="text-xs text-black/40 mt-2">{selectedInsight.enquiry.sender_name} · {displayEmail(selectedInsight.enquiry.sender_email)}</div>
                  </div>
                  <InsightPanel data={{ ai_output: selectedInsight.enquiry.ai_output, metadata: selectedInsight.actions?.[0]?.metadata, source: selectedInsight.enquiry.source, ai_confidence: selectedInsight.enquiry.ai_confidence }} />
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {selectedInsight.actions.map((a: any) => (
                      <div key={a.id} className="border border-black/10 rounded-xl p-3">
                        <div className="text-xs text-black/40 uppercase">Suggested Next Step · {a.status.replace(/_/g, " ")}</div>
                        <div className="font-medium mt-1">{labelAction(a.action_type)}</div>
                        <div className="text-xs mt-1">Responsible Team: {labelTeam(a.metadata?.suggested_team)} · Person in Charge: {a.metadata?.assigned_owner}</div>
                        {a.draft_response && <div className="text-sm mt-2 italic">“{a.draft_response}”</div>}
                        <div className="text-xs text-black/50 mt-2">Confidence {a.confidence ? Math.round(a.confidence*100)+"%" : "—"} · Needs your approval before any change</div>
                      </div>
                    ))}
                  </div>
                  <details className="border border-black/10 rounded-xl">
                    <summary className="px-3 py-2 text-sm cursor-pointer">Show technical details for troubleshooting</summary>
                    <pre className="m-3 p-3 bg-black/[0.03] rounded-xl text-xs overflow-auto max-h-64">{JSON.stringify({ ai_output: selectedInsight.enquiry.ai_output, actions: selectedInsight.actions, recentActivity: selectedInsight.audit.slice(0,8) }, null, 2)}</pre>
                  </details>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Confirm delete modal — minimal black & white */}
        {confirmDelete && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30" onClick={() => setConfirmDelete(null)}>
            <div className="bg-white rounded-2xl max-w-[420px] w-full p-6" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold">{confirmDelete.type === "insight" ? "Delete Insight?" : "Delete Customer?"}</h3>
              <p className="text-sm text-black/60 mt-2">
                {confirmDelete.type === "insight"
                  ? `This will permanently delete the enquiry and its insight for "${confirmDelete.label}". Actions and audit for this enquiry will also be removed.`
                  : `This will permanently delete customer "${confirmDelete.label}" and unlink related enquiries.`}
              </p>
              <p className="text-xs text-black/40 mt-2">This cannot be undone.</p>
              <div className="mt-6 flex gap-2 justify-end">
                <button onClick={() => setConfirmDelete(null)} disabled={deleting} className="h-9 px-4 border border-black/10 rounded-full text-sm hover:bg-black/[0.03] disabled:opacity-40">Cancel</button>
                <button
                  onClick={() => (confirmDelete.type === "insight" ? handleDeleteInsight(confirmDelete.id) : handleDeleteCustomer(confirmDelete.id))}
                  disabled={deleting}
                  className="h-9 px-4 bg-black text-white rounded-full text-sm inline-flex items-center gap-1.5 hover:bg-black/90 disabled:opacity-40"
                >
                  <Trash2 className="w-4 h-4" /> {deleting ? "Deleting…" : "Delete"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      <footer className="max-w-[1220px] mx-auto px-6 py-6 border-t border-black/10 mt-8">
        <div className="text-xs text-black/40 text-center">InboxOps · Smart routing for everyday users · Human approves every important change · <a href="http://localhost:8000/docs" target="_blank" className="underline">Developer Docs</a></div>
      </footer>

      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 space-y-2">
        {toasts.map((t) => (
          <div key={t.id} className="px-3 py-2 bg-black text-white rounded-full text-sm shadow-lg">{t.message}</div>
        ))}
      </div>
    </div>
  );
}
