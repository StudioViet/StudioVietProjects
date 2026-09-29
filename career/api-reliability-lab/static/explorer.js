"use strict";
const $ = id => document.getElementById(id);
const sample = {external_reference:"DEMO-1042",asset_id:"ASSET-0042",action:"inspect",priority:"normal"};
let spec, operations = [], selected, activeView = "body", busy = false;
let result = null, history = [], latestOrder = "wo_000000000000";
const key = () => "explorer-" + crypto.randomUUID();
const pretty = value => JSON.stringify(value, null, 2);
const resolve = value => value?.$ref ? value.$ref.split("/").slice(1).reduce((v,k)=>v[k],spec) : value;
const isOrder = () => selected.path === "/api/v1/work-orders" && selected.method === "post" || selected.path.endsWith("/provider-probe");
function showOutput(){
  document.querySelectorAll("[data-view]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.view===activeView)));
  if (!result) return;
  const views = {body:typeof result.body === "string" ? result.body : pretty(result.body), headers:pretty(result.headers),
    trace:result.body?.meta?.trace?.length ? pretty(result.body.meta.trace) : "No retry trace. The provider probe makes one attempt. Integration validation/authentication failures stop before provider work.", curl:result.curl};
  $("response-output").textContent = views[activeView];
}
function selectOperation(index){
  if (busy) return;
  selected = operations[index];
  document.querySelectorAll(".endpoint").forEach((b,i)=>b.setAttribute("aria-pressed",String(i===index)));
  $("operation-title").textContent = selected.op.summary;
  $("method").textContent = selected.method.toUpperCase();
  $("path").textContent = selected.path;
  const probe = selected.path.endsWith("/provider-probe");
  $("operation-help").textContent = probe ? "One request to the mock provider, with its original HTTP status and body. Provider-only orders are not registered with the integration. Re-execute with the same key to inspect recovery or a conflict." :
    selected.path === "/api/v1/work-orders" && selected.method === "post" ? "The full integration: authenticate, validate, and retry transient failures. Compare the final status with the provider statuses in the retry trace." :
    selected.path.endsWith("/webhook-deliveries") ? "Local signing helper. Create an integration order first, then deliver a valid, tampered, or expired event. Signing secrets stay on the server." :
    selected.path.endsWith("/webhooks/provider") ? "Raw webhook receiver: requires an HMAC signature and timestamp. Use the webhook-deliveries helper for correctly signed demo requests." : "Edit the parameters, execute a request, and inspect the service’s response.";
  const headers = {"Authorization":"Bearer demo-client-token"};
  if (selected.method === "post") headers["Content-Type"] = "application/json";
  if (isOrder()) Object.assign(headers,{"Idempotency-Key":key(),"X-Lab-Scenario":"healthy"});
  if(selected.path.endsWith("/webhooks/provider")){delete headers.Authorization;headers["X-Webhook-Timestamp"]="";headers["X-Webhook-Signature"]="";}
  $("headers").value = pretty(headers);
  $("parameters").replaceChildren();
  for(const param of (selected.op.parameters || []).filter(p=>["path","query"].includes(p.in))){
    const row=document.createElement("div");row.className="parameter";
    const label=document.createElement("label");label.htmlFor="param-"+param.name;label.textContent=param.name+" ("+param.in+")";
    const input=document.createElement("input");input.id=label.htmlFor;input.dataset.name=param.name;input.dataset.location=param.in;
    input.value=param.name==="order_id"?latestOrder:resolve(param.schema)?.default??"";
    input.placeholder=param.required?"Required":"Optional";row.append(label,input);$("parameters").append(row);
  }
  const bodySchema=resolve(selected.op.requestBody?.content?.["application/json"]?.schema);
  $("schema").textContent=bodySchema?pretty(bodySchema):"This operation has no JSON request body.";
  $("body").disabled=selected.method!=="post";
  $("body").value=isOrder()?pretty(sample):selected.path.endsWith("/webhook-deliveries")?pretty({work_order_id:latestOrder,event_id:"evt_explorer",mode:"valid"}):selected.path.endsWith("/webhooks/provider")?pretty({id:"evt_explorer",type:"work_order.completed",work_order_id:latestOrder}):"";
  $("contract").replaceChildren();
  for(const [code,info] of Object.entries(selected.op.responses||{})){const badge=document.createElement("span");badge.textContent=code+" · "+info.description;$("contract").append(badge);}
  $("preset").disabled=$("load-preset").disabled=$("new-key").disabled=!isOrder();
  $("preset").value="healthy";$("request-feedback").textContent="";
}
function loadPreset(){
  if(!isOrder()||busy)return;
  const p=$("preset").value;
  $("headers").value=pretty({Authorization:"Bearer "+(p==="bad_auth"?"invalid-token":"demo-client-token"),"Content-Type":"application/json","Idempotency-Key":key(),"X-Lab-Scenario":["bad_auth","invalid","malformed"].includes(p)?"healthy":p});
  $("body").value=p==="malformed"?'{"external_reference": "DEMO-1042",':pretty({...sample,asset_id:p==="invalid"?"INVALID-ASSET":sample.asset_id});
  $("request-feedback").textContent="Example loaded with a fresh key. Execute to send.";
}
function buildRequest(){
  const parsed=JSON.parse($("headers").value);
  if(!parsed || Array.isArray(parsed) || typeof parsed!=="object" || Object.values(parsed).some(v=>typeof v!=="string"))throw new Error("Headers must be a JSON object with string values.");
  const headers=new Headers(parsed);
  // Restrict this explorer to documented, same-origin API routes. No URL proxy.
  let path=selected.path;const query=new URLSearchParams();
  for(const input of $("parameters").querySelectorAll("input")){
    if(input.dataset.location==="path"){if(!input.value)throw new Error(input.dataset.name+" is required.");path=path.replace("{"+input.dataset.name+"}",encodeURIComponent(input.value));}
    else if(input.value)query.set(input.dataset.name,input.value);
  }
  const url=location.origin+path+(query.size?"?"+query.toString():"");
  const body=selected.method==="post"?$("body").value:undefined;
  const quote=s=>"'"+s.replaceAll("'","'\\''")+"'";
  const curl=["# Bash / macOS / Linux syntax", "curl -i -X "+selected.method.toUpperCase()+" "+quote(url),...Array.from(headers,([k,v])=>"  -H "+quote(k+": "+v)),...(body!==undefined?["  --data-raw "+quote(body)]:[])];
  return {url,headers,body,curl:curl[0]+"\n"+curl.slice(1).join(" \\\n")};
}
function diagnosis(status,body,headers){
  const trace=body?.meta?.trace||[];
  if(status<400){if(headers["idempotency-replayed"]==="true")return "Recovered the original work order. Reusing the same key and body prevented a second provider write.";
    if(trace.some(t=>t.status>=400))return "Recovered successfully. The customer received "+status+", while the provider returned "+trace.map(t=>t.status).join(" → ")+". Open Retry trace to inspect the decisions.";
    return isOrder()?"Request succeeded. For a 409 conflict, keep this key, change the request body, and execute again. For a safe replay, keep both unchanged.":"Request succeeded. Inspect the response body and headers for the resource or event result.";}
  if(status===401)return headers["x-lab-response-source"]==="mock-provider"?"The provider rejected the server’s credentials. Customer credentials were accepted. The full integration translates this into 502.":body?.error?.code?.includes("signature")?"Webhook signature verification failed. Use the local signing helper to compare a valid event with a tampered or expired event.":"The integration rejected the caller token. Correct Authorization before retrying; the provider was not contacted.";
  if(status===422)return "Request validation failed. Inspect the field paths in the response, correct the body or headers, then retry. Malformed JSON is sent to the server as written.";
  if(status===409)return "This key already belongs to different data. Restore the original body for a replay, or use a new key only if this is a genuinely new operation.";
  if(status===429)return "The provider rate limited this request. Retry-After: "+(headers["retry-after"]||"not supplied")+" s. The probe does not retry automatically.";
  if(status===504)return "A response was lost after the mock provider committed the write. The caller cannot infer failure. Execute again with the same key and body to recover the original work order.";
  if(status===502)return "The caller authenticated successfully, but the provider rejected the integration’s credentials. Escalate the provider configuration; changing the customer token will not fix it.";
  if(status===503)return body?.meta?.stop_reason==="wait_budget"?"The provider’s requested wait exceeds the lab’s waiting budget. The integration stopped and returned Retry-After; it did not retry too early.":body?.meta?.stop_reason==="attempt_limit"?"The provider remained unavailable after three attempts. Stop automatic retries and investigate or escalate.":"The mock provider is unavailable. This probe makes one attempt; the integration endpoint demonstrates bounded retries.";
  return "Inspect the error message and request ID before choosing the next action.";
}
async function execute(){
  if(busy)return;
  let request;try{request=buildRequest();}catch(e){$("request-feedback").textContent=e.message;return;}
  busy=true;document.querySelectorAll("button,select,input,textarea").forEach(e=>e.disabled=true);
  $("response-status").textContent="SENDING";$("response-status").className="status";$("request-feedback").textContent="";
  const started=performance.now();
  try{
    const response=await fetch(request.url,{method:selected.method.toUpperCase(),headers:request.headers,body:request.body,redirect:"error",signal:AbortSignal.timeout(15000)});
    const raw=await response.text();let body;try{body=JSON.parse(raw);}catch{body=raw;}
    const headers=Object.fromEntries(response.headers);const elapsed=Math.round(performance.now()-started);
    result={body,headers,curl:request.curl};
    if(selected.path==="/api/v1/work-orders"&&selected.method==="post"&&body?.data?.id)latestOrder=body.data.id;
    $("response-status").textContent=response.status+" "+response.statusText;$("response-status").className="status "+(response.ok?"good":"bad");
    $("response-source").textContent="Source: "+(headers["x-lab-response-source"]||"server");$("response-time").textContent=elapsed+" ms";$("response-id").textContent="Request ID: "+(headers["x-request-id"]||"—");
    $("diagnosis").textContent=diagnosis(response.status,body,headers);$("diagnosis").className="diagnosis"+(response.ok?"":" bad");
    history.unshift(response.status+" · "+selected.method.toUpperCase()+" "+new URL(request.url).pathname+" · "+elapsed+" ms");history=history.slice(0,8);
    $("history").replaceChildren(...history.map(text=>{const li=document.createElement("li");li.textContent=text;return li;}));
    activeView="body";showOutput();
  }catch(e){
    result={body:{error:"Browser request failed or timed out. The write outcome may be unknown; preserve the idempotency key before retrying.",detail:e.message},headers:{},curl:request.curl};
    $("response-status").textContent="NO HTTP RESPONSE";$("response-status").className="status bad";
    $("response-source").textContent="Source: browser / transport";$("response-time").textContent=Math.round(performance.now()-started)+" ms";$("response-id").textContent="Request ID: unavailable";
    $("diagnosis").textContent="No server status was received. Check the local server and preserve the request key when investigating an uncertain write.";$("diagnosis").className="diagnosis bad";activeView="body";showOutput();
  }finally{
    busy=false;document.querySelectorAll("button,select,input,textarea").forEach(e=>e.disabled=false);
    $("preset").disabled=$("load-preset").disabled=$("new-key").disabled=!isOrder();$("body").disabled=selected.method!=="post";
  }
}
$("execute").addEventListener("click",execute);
$("load-preset").addEventListener("click",loadPreset);
$("new-key").addEventListener("click",()=>{try{const h=JSON.parse($("headers").value);for(const name of Object.keys(h))if(name.toLowerCase()==="idempotency-key")delete h[name];h["Idempotency-Key"]=key();$("headers").value=pretty(h);$("request-feedback").textContent="New key = new operation. Body unchanged.";}catch{$("request-feedback").textContent="Correct the headers JSON first.";}});
$("copy-curl").addEventListener("click",async()=>{try{const r=buildRequest();await navigator.clipboard.writeText(r.curl);$("request-feedback").textContent="Copied current request as Bash cURL, including entered headers.";}catch(e){$("request-feedback").textContent=e.message;}});
document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>{activeView=b.dataset.view;showOutput();}));
(async()=>{
  try{
    const response=await fetch("/openapi.json");if(!response.ok)throw new Error("OpenAPI unavailable");spec=await response.json();
    for(const [path,methods] of Object.entries(spec.paths))for(const [method,op]of Object.entries(methods))if(["get","post"].includes(method)&&path.startsWith("/api/"))operations.push({path,method,op});
    operations.sort((a,b)=>Number(b.path.endsWith("/provider-probe"))-Number(a.path.endsWith("/provider-probe")));
    $("endpoints").replaceChildren(...operations.map((item,i)=>{const b=document.createElement("button");b.className="endpoint";const method=document.createElement("b");method.textContent=item.method.toUpperCase();method.className=item.method;const path=document.createElement("code");path.textContent=item.path;const description=document.createElement("small");description.textContent=item.op.summary;b.append(method,path,description);b.addEventListener("click",()=>selectOperation(i));return b;}));
    selectOperation(0);$("preset").value="rate_limit";loadPreset();
  }catch(e){$("endpoints").textContent=e.message;$("execute").disabled=true;$("copy-curl").disabled=true;$("operation-title").textContent="Could not load API contract";}
})();
