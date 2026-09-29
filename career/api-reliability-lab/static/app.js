const $ = (id) => document.getElementById(id);
const scenarios = [
  {id:"healthy",title:"Healthy request",short:"201 · accepted",description:"A valid, authenticated request creates one work order. Inspect the resource ID and Location header.",lesson:"Establish a working baseline before investigating a failure. A 201 response means the provider accepted a new resource; it does not mean the field work is complete."},
  {id:"lost_response",title:"Response lost after commit",short:"504 → 201 · recover safely",description:"The mock provider creates the work order, then drops the response. The integration cannot initially tell whether creation succeeded.",lesson:"A timeout does not prove failure. Retrying with the SAME idempotency key lets the provider return the original result. Generating a new key could create a duplicate work order."},
  {id:"rate_limit",title:"Rate limit",short:"429 → 201 · respect Retry-After",description:"The provider returns 429 and asks the client to wait one second. Watch the integration honor that delay before retrying.",lesson:"Respect the provider's Retry-After instead of immediately adding more load. Retrying a write also requires a stable key and an idempotency contract with the provider."},
  {id:"unavailable",title:"Temporary outage",short:"503 → 503 → 201 · bounded backoff",description:"Two requests fail before the provider recovers. The integration uses increasing delays with a little jitter and a three-attempt cap.",lesson:"Backoff and jitter reduce synchronized retry bursts. A limit prevents one customer request from keeping resources occupied indefinitely."},
  {id:"bad_auth",title:"Invalid caller token",short:"401 · fix authentication",description:"This request deliberately uses an invalid lab token. It must be rejected before reaching the provider.",lesson:"A caller's invalid token needs correction, not repeated requests. It should produce zero provider attempts and zero work orders."},
  {id:"invalid_payload",title:"Invalid payload",short:"422 · field-level feedback",description:"The asset identifier does not match the API contract. The response identifies the field to fix without echoing the submitted data.",lesson:"Validation errors are actionable input problems. Retrying unchanged data wastes capacity and delays a useful explanation to the customer."},
  {id:"duplicate",title:"Repeat the same request",short:"201 → 201 · one work order",description:"Send the same body twice with the same idempotency key. Compare the returned IDs and the number of provider work orders created.",lesson:"Idempotency is a provider-backed guarantee, not just a header. Identical retries return the original response; only one side effect is created."},
  {id:"conflict",title:"Reuse a key with new data",short:"201 → 409 · reject ambiguity",description:"After creating an order, change its priority but keep its idempotency key. The provider rejects this conflicting reuse.",lesson:"Store a payload fingerprint alongside the key. A changed request must not silently inherit the result of a different operation."},
  {id:"provider_auth",title:"Provider credential failure",short:"Upstream 401 · client receives 502",description:"The lab caller is authenticated, but the integration's provider credential is deliberately wrong. Follow the distinction in the trace.",lesson:"A provider's 401 is an integration configuration problem, not a reason to tell your authenticated customer their token is wrong. Stop and investigate the server-side credential."},
  {id:"permanent_failure",title:"Provider stays unavailable",short:"503 × 3 · stop and escalate",description:"The provider does not recover. The integration stops after three attempts and returns a request ID for investigation.",lesson:"Retries are a recovery tactic, not a resolution strategy. After a bounded attempt budget, preserve the evidence and communicate the next step."},
  {id:"long_rate_limit",title:"Wait exceeds the budget",short:"429 · defer instead of retrying early",description:"The provider asks for 60 seconds. This interactive request has a three-second waiting budget, so the integration stops instead of shortening the requested wait.",lesson:"Capping Retry-After and retrying early would violate the provider's instruction. A real service could queue a deferred attempt; this lab returns a retryable unavailable response."}
];
let selected = scenarios[1], activeOrder = null, busy = false;
const basePayload = () => ({external_reference:"DEMO-1042",asset_id:"ASSET-0042",action:"inspect",priority:"normal"});
function setBusy(value) {
  busy = value;
  document.querySelectorAll(".scenario,#run").forEach(b => b.disabled = value);
  document.querySelectorAll("[data-webhook]").forEach(b => b.disabled = value || !activeOrder);
  $("payload").disabled = value;
}
function selectScenario(scenario) {
  selected = scenario;
  document.querySelectorAll(".scenario").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.id === scenario.id)));
  $("scenario-title").textContent = scenario.title;
  $("scenario-description").textContent = scenario.description;
  $("lesson").textContent = scenario.lesson;
  const payload = basePayload();
  if (scenario.id === "invalid_payload") payload.asset_id = "wrong-format";
  $("payload").value = JSON.stringify(payload, null, 2);
  $("status").textContent = "READY"; $("status").className = "status";
}
scenarios.forEach((s,i) => {
  const button = document.createElement("button"); button.className = "scenario"; button.dataset.id = s.id;
  const number = document.createElement("span"); number.className = "scenario-number"; number.textContent = String(i+1).padStart(2,"0");
  const words = document.createElement("span"), title = document.createElement("strong"), short = document.createElement("small");
  title.textContent=s.title;short.textContent=s.short;words.append(title,short);button.append(number,words);
  button.onclick=()=>selectScenario(s);$("scenarios").append(button);
});
const headers = () => ({"Authorization":`Bearer ${$("token").value}`,"Content-Type":"application/json"});
async function request(url, options={}) {
  const response = await fetch(url, {...options, headers:{...headers(),...options.headers}});
  let body; try { body=await response.json(); } catch { body={error:{message:"Response was not JSON"}}; }
  return {status:response.status,headers:{"X-Request-ID":response.headers.get("X-Request-ID"),"Location":response.headers.get("Location"),"Idempotency-Replayed":response.headers.get("Idempotency-Replayed"),"Retry-After":response.headers.get("Retry-After")},body};
}
function drawTrace(results) {
  $("trace").replaceChildren(); let count=0;
  results.forEach((result, index)=>{
    const trace=result.body.meta?.trace || [];
    const rows=trace.length?trace:[{status:result.status,action:result.body.error?.message || "No provider call",attempt:"—"}];
    count+=trace.length;
    rows.forEach(row=>{
      const li=document.createElement("li"),code=document.createElement("span"),message=document.createElement("span");
      code.className="trace-code"+(row.status>=400?" error":"");code.textContent=row.status;
      message.textContent=`${results.length>1?`Request ${index+1} · `:""}${row.attempt!=="—"?`Attempt ${row.attempt} · `:""}${row.action}${row.delay_seconds?` (${row.delay_seconds}s)`:""}`;
      li.append(code,message);$("trace").append(li);
    });
  });
  $("metric-attempts").textContent=count;
}
$("run").onclick=async()=>{
  if(busy)return;
  let payload;try{payload=JSON.parse($("payload").value);}catch{$("status").textContent="INVALID JSON";$("status").className="status bad";$("response").textContent="Fix the JSON syntax before sending.";return;}
  setBusy(true);$("status").textContent="RUNNING";$("status").className="status";
  const started=performance.now(),key="demo_"+crypto.randomUUID().replaceAll("-","");
  try{
    const before=await request("/api/v1/lab/stats");
    const scenario=["bad_auth","invalid_payload","duplicate","conflict"].includes(selected.id)?"healthy":selected.id;
    const h={"Idempotency-Key":key,"X-Lab-Scenario":scenario};
    if(selected.id==="bad_auth")h.Authorization="Bearer invalid-for-this-scenario";
    const results=[await request("/api/v1/work-orders",{method:"POST",headers:h,body:JSON.stringify(payload)})];
    if(["duplicate","conflict"].includes(selected.id)&&results[0].status<400){
      if(selected.id==="conflict")payload.priority=payload.priority==="urgent"?"normal":"urgent";
      results.push(await request("/api/v1/work-orders",{method:"POST",headers:h,body:JSON.stringify(payload)}));
    }
    const after=await request("/api/v1/lab/stats");const last=results.at(-1);
    $("metric-writes").textContent=before.status===200&&after.status===200?after.body.provider_orders_created-before.body.provider_orders_created:"—";
    $("metric-time").textContent=((performance.now()-started)/1000).toFixed(2)+"s";
    $("status").textContent="HTTP "+last.status;$("status").className="status "+(last.status<400?"good":"bad");
    $("request-id").textContent=last.headers["X-Request-ID"];$("request-id").title=last.headers["X-Request-ID"];
    $("response").textContent=JSON.stringify(results.length===1?last:results,null,2);drawTrace(results);
    const success=results.find(r=>r.status<400&&r.body.data?.id);
    activeOrder=success?.body.data.id||null;$("active-order").textContent=activeOrder||"None in this experiment";
    $("webhook-response").textContent=activeOrder?"Choose a signed-event scenario below.":"Run a successful work-order scenario first.";
  }catch(error){$("status").textContent="CONNECTION ERROR";$("status").className="status bad";$("response").textContent=String(error);}
  finally{setBusy(false);}
};
document.querySelectorAll("[data-webhook]").forEach(button=>button.onclick=async()=>{
  if(busy||!activeOrder)return;setBusy(true);
  try{
    const mode=button.dataset.webhook,eventId="evt_"+crypto.randomUUID().replaceAll("-","");
    const payload={work_order_id:activeOrder,event_id:eventId,mode:mode==="duplicate"?"valid":mode};
    const deliveries=[await request("/api/v1/lab/webhook-deliveries",{method:"POST",body:JSON.stringify(payload)})];
    if(mode==="duplicate")deliveries.push(await request("/api/v1/lab/webhook-deliveries",{method:"POST",body:JSON.stringify(payload)}));
    const order=await request(`/api/v1/work-orders/${activeOrder}`);
    $("webhook-response").textContent=JSON.stringify({deliveries,work_order:order.body.data},null,2);
  }catch(error){$("webhook-response").textContent=String(error);}finally{setBusy(false);}
});
selectScenario(selected);
