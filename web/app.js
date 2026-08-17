const state = { catalog: [], byName: new Map(), roster: [], scanId: null, scanPoll: null, lastResult: null, quickSimSequence: 0 };
const $ = (id) => document.getElementById(id);

function setTheme(theme) {
  document.documentElement.dataset.theme=theme;
  localStorage.setItem("maaBaseTheme",theme);
  $("themeToggle").textContent=theme==="light" ? "◐ 深色" : "☀︎ 浅色";
}
setTheme(localStorage.getItem("maaBaseTheme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
$("themeToggle").addEventListener("click",()=>setTheme(document.documentElement.dataset.theme==="light" ? "dark" : "light"));

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function saveRoster() {
  localStorage.setItem("maaBaseRoster", JSON.stringify(state.roster));
}

function renderRoster() {
  $("rosterCount").textContent = state.roster.length;
  const body = $("rosterBody");
  if (!state.roster.length) {
    body.innerHTML = '<tr><td colspan="3" class="empty">尚未导入干员</td></tr>';
    saveRoster();
    return;
  }
  body.innerHTML = state.roster.map((op, index) => `
    <tr>
      <td><strong>${escapeHtml(op.name)}</strong></td>
      <td><select data-index="${index}" data-field="elite">
        ${[0,1,2].map(v => `<option value="${v}" ${v === +op.elite ? "selected" : ""}>精英 ${v}</option>`).join("")}
      </select></td>
      <td><button class="remove quiet danger" data-remove="${index}">移除</button></td>
    </tr>`).join("");
  body.querySelectorAll("[data-field]").forEach(input => input.addEventListener("change", event => {
    const target = event.currentTarget;
    state.roster[+target.dataset.index][target.dataset.field] = +target.value;
    saveRoster();
  }));
  body.querySelectorAll("[data-remove]").forEach(button => button.addEventListener("click", event => {
    state.roster.splice(+event.currentTarget.dataset.remove, 1);
    renderRoster();
  }));
  saveRoster();
}

function message(id, text, error = false) {
  const node = $(id);
  node.textContent = text;
  node.className = `message${error ? " error" : ""}`;
}

function hideMessage(id) { $(id).className = "message hidden"; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c])); }
function number(value) { return new Intl.NumberFormat("zh-CN").format(value); }

async function loadCatalog() {
  const data = await request("/api/operators");
  state.catalog = data.operators;
  state.byName = new Map(state.catalog.map(op => [op.name, op]));
  $("operatorList").innerHTML = state.catalog.map(op => `<option value="${escapeHtml(op.name)}">${op.rarity}★</option>`).join("");
  $("catalogStatus").textContent = `${data.count} 名干员 · 本地数据就绪`;
  try {
    const stored = await request("/api/roster");
    if (stored.operators.length) state.roster = stored.operators;
    else state.roster = JSON.parse(localStorage.getItem("maaBaseRoster") || "[]").filter(op => state.catalog.some(x => x.id === op.id));
  } catch (_) {
    try { state.roster = JSON.parse(localStorage.getItem("maaBaseRoster") || "[]"); }
    catch (_) { state.roster = []; }
  }
  renderRoster();
}

async function saveRosterToServer() {
  const data = await request("/api/roster", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({operators:state.roster})});
  state.roster = data.operators; renderRoster();
  message("importMessage", `已将 ${data.count} 名干员保存到本机。`);
}

function stopScanPoll() {
  if (state.scanPoll) clearInterval(state.scanPoll);
  state.scanPoll = null;
}

function resetScanUi() {
  stopScanPoll(); state.scanId = null;
  $("sklandQr").style.display = "none"; $("sklandQr").removeAttribute("src");
  $("qrPlaceholder").style.display = "block"; $("qrPlaceholder").textContent = "正在生成二维码…";
  $("accountPicker").classList.add("hidden"); $("confirmSklandButton").classList.add("hidden");
  $("retrySklandButton").classList.add("hidden");
  message("sklandMessage", "正在连接鹰角登录服务…");
}

async function startSklandScan() {
  resetScanUi();
  try {
    const data = await request("/api/skland/scan/start", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    state.scanId = data.scan_id;
    $("sklandQr").src = data.qr_data_uri; $("sklandQr").style.display = "block"; $("qrPlaceholder").style.display = "none";
    message("sklandMessage", "等待扫码确认…请在森空岛 App 中完成授权。");
    state.scanPoll = setInterval(checkSklandScan, 1800);
  } catch (error) {
    message("sklandMessage", error.message, true); $("retrySklandButton").classList.remove("hidden");
  }
}

async function checkSklandScan() {
  if (!state.scanId) return;
  try {
    const data = await request(`/api/skland/scan/status?scan_id=${encodeURIComponent(state.scanId)}`);
    if (data.status !== "authorized") return;
    stopScanPoll();
    $("sklandAccount").innerHTML = data.accounts.map(account => `<option value="${escapeHtml(account.uid)}">${escapeHtml(account.nickname)} · ${escapeHtml(account.channel_name)} · ${escapeHtml(account.uid)}${account.is_default ? "（默认）" : ""}</option>`).join("");
    $("accountPicker").classList.remove("hidden"); $("confirmSklandButton").classList.remove("hidden");
    message("sklandMessage", "授权成功。请选择要导入的游戏角色。请输入或确认后即可保存干员与练度。");
  } catch (error) {
    stopScanPoll(); message("sklandMessage", error.message, true); $("retrySklandButton").classList.remove("hidden");
  }
}

$("sklandButton").addEventListener("click", () => { $("sklandDialog").showModal(); startSklandScan(); });
$("closeSklandButton").addEventListener("click", () => { stopScanPoll(); $("sklandDialog").close(); });
$("retrySklandButton").addEventListener("click", startSklandScan);
$("saveButton").addEventListener("click", () => saveRosterToServer().catch(error => message("importMessage", error.message, true)));
$("confirmSklandButton").addEventListener("click", async () => {
  const button = $("confirmSklandButton"); button.disabled = true; button.textContent = "正在读取干员列表…";
  try {
    const data = await request("/api/skland/import", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({scan_id:state.scanId, uid:$("sklandAccount").value})});
    state.roster = data.operators; renderRoster(); stopScanPoll(); $("sklandDialog").close();
    message("importMessage", `已从森空岛导入并保存 ${data.count} 名干员（${data.account.nickname}）。`);
  } catch (error) { message("sklandMessage", error.message, true); }
  finally { button.disabled = false; button.textContent = "导入并保存此角色的干员列表"; }
});

$("importButton").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    const raw = JSON.parse(await file.text());
    const data = await request("/api/import", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(raw)});
    state.roster = data.operators;
    renderRoster();
    message("importMessage", `已导入 ${data.operators.length} 名干员${data.warnings.length ? `；${data.warnings.length} 条未匹配记录` : ""}`);
  } catch (error) { message("importMessage", error.message, true); }
  event.target.value = "";
});

$("addButton").addEventListener("click", () => {
  const name = $("operatorSearch").value.trim();
  const op = state.byName.get(name);
  if (!op) return message("importMessage", "请选择列表中的干员名称", true);
  if (state.roster.some(x => x.id === op.id)) return message("importMessage", `${name} 已在列表中`, true);
  state.roster.push({id:op.id, name:op.name, elite:2, level:1, potential:1});
  $("operatorSearch").value = "";
  hideMessage("importMessage"); renderRoster();
});
$("operatorSearch").addEventListener("keydown", event => { if (event.key === "Enter") $("addButton").click(); });
$("clearButton").addEventListener("click", () => { state.roster = []; renderRoster(); });

const layoutSizes = {243:{trade:2,factory:4},153:{trade:1,factory:5},333:{trade:3,factory:3}};
function updateLayoutControls() {
  const layout=layoutSizes[$("baseLayout").value];
  const previousExp=+("value" in $("expFactories") ? $("expFactories").value : 1) || 1;
  const previousShard=+$('shardFactories').value || 0;
  $("expFactories").innerHTML=Array.from({length:layout.factory+1},(_,i)=>`<option value="${i}">${i} 间</option>`).join("");
  $("shardFactories").innerHTML=Array.from({length:layout.factory+1},(_,i)=>`<option value="${i}">${i} 间</option>`).join("");
  $("expFactories").value=Math.min(previousExp,layout.factory);
  $("shardFactories").value=Math.min(previousShard,layout.factory-(+$("expFactories").value));
  updateProductControls();
}
function updateProductControls() {
  const layout=layoutSizes[$("baseLayout").value];
  let exp=+$("expFactories").value, shard=+$("shardFactories").value;
  if(exp+shard>layout.factory){shard=Math.max(0,layout.factory-exp);$("shardFactories").value=shard;}
  const gold=layout.factory-exp-shard;
  $("goldFactoryHint").textContent=`剩余 ${gold} 间制造站生产赤金`;
  const prev=+$("orundumTrades").value||0;
  $("orundumTrades").innerHTML=Array.from({length:layout.trade+1},(_,i)=>`<option value="${i}">${i} 间</option>`).join("");
  $("orundumTrades").value=shard ? Math.max(1,Math.min(prev||1,layout.trade)) : Math.min(prev,layout.trade);
  $("shardRecipe").disabled=!shard;
}
$("baseLayout").addEventListener("change",updateLayoutControls);
$("expFactories").addEventListener("change",updateProductControls);
$("shardFactories").addEventListener("change",updateProductControls);
$("scheduleMode").addEventListener("change",()=>{
  if($("scheduleMode").value==="fixed" && ![8,12].includes(+("value" in $("shiftHours") ? $("shiftHours").value : 8))) $("shiftHours").value="8";
});
updateLayoutControls();

$("optimizeButton").addEventListener("click", async () => {
  hideMessage("solveMessage");
  if (state.roster.length < 21) return message("solveMessage", "请先导入至少 21 名有效干员。", true);
  if ($("scheduleMode").value === "fixed" && ![8,12].includes(+("value" in $("shiftHours") ? $("shiftHours").value : 8))) return message("solveMessage", "固定轮班请选择 8 或 12 小时。", true);
  const button = $("optimizeButton"); button.disabled = true; button.textContent = "正在枚举并协调候选组合…";
  const payload = {
    operators: state.roster,
    base_layout: $("baseLayout").value,
    exp_factories: +$("expFactories").value,
    shard_factories: +$("shardFactories").value,
    orundum_trades: +$("orundumTrades").value,
    shard_recipe: $("shardRecipe").value,
    drone_target: $("droneTarget").value,
    gold_net_target_per_day: +$("goldNetTarget").value || 0,
    objective_mode: $("objectiveMode").value,
    schedule_mode: $("scheduleMode").value,
    lock_dorm_helper: $("lockDormHelper").checked,
    enable_fiammetta: $("enableFiammetta").checked,
    shift_hours: +$("shiftHours").value,
    max_work_hours: +$("shiftHours").value,
    morale_floor: 1,
    collection_interval_hours: +$("collectionInterval").value,
    external_gold_per_day: (+$("dailyGold").value || 0) + (+$("weeklyGold").value || 0) / 7,
    gold_inventory: +$("goldInventory").value || 0,
    shard_inventory: +$("shardInventory").value || 0,
    include_rotation: true,
    candidate_limit: 320,
  };
  try {
    const data = await request("/api/optimize", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    renderResults(data);
  } catch (error) { message("solveMessage", error.message, true); }
  finally { button.disabled = false; button.textContent = "计算候选集排班"; }
});

function renderResults(data) {
  state.lastResult = data;
  const m = data.rotation?.average_metrics || data.metrics;
  $("results").classList.remove("hidden");
  $("solverBadge").textContent = data.solver;
  $("lmdKpi").textContent = number(m.lmd_per_day);
  $("expKpi").textContent = number(m.exp_per_day);
  $("goldKpi").textContent = `${m.gold_net_per_day >= 0 ? "+" : ""}${m.gold_net_per_day}`;
  $("goldKpi").style.color = m.gold_net_per_day < 0 ? "var(--red)" : "var(--gold)";
  $("goldKpiNote").textContent = `站内 ${signed(m.gold_production_net_per_day)} · 外部 +${m.gold_external_per_day}`;
  $("droneKpi").textContent = number(m.drones_per_day);
  $("droneKpiNote").textContent = `发电站 +${m.power_bonus}% · 等效 ${m.drone_hours_per_day} 小时`;
  renderObjectiveComparison(data.objective,m);
  renderProductionMonitor(m);
  renderGoldMonitor(m);
  renderDroneMonitor(m);
  renderCrossRoomFlows(data.cross_room_flows || []);
  renderBars(m);
  renderRotation(data.rotation);
  renderYieldCurve(data.rotation?.production_curve);
  const audit=data.search_audit;
  const valuation=data.valuation, objective=data.objective;
  const comparison=objective?.comparison;
  const objectiveAudit=comparison ? (comparison.same_semantic_assignment && comparison.same_work_durations!==false ? `目标交叉审计：在${comparison.scope}内，“${objective.label}”和“${comparison.alternate_label}”收敛到相同的实质房间组合与工时（已忽略同类房间编号互换）；这是本 Box 的求解结果，不代表两套公式相同。` : `目标交叉审计：“${objective.label}”与“${comparison.alternate_label}”在完整 A/B 组合或工时上存在差异；备选方案龙门币 ${comparison.alternate_metrics.lmd_per_day}/日、经验 ${comparison.alternate_metrics.exp_per_day}/日、赤金净流 ${signed(comparison.alternate_metrics.gold_net_per_day)}/日${comparison.alternate_work_durations?`，工时 A ${comparison.alternate_work_durations.A}h / B ${comparison.alternate_work_durations.B}h`:""}。`) : "";
  const searchWarning=audit ? `求解范围：${audit.claim}。${audit.candidate_operator_pool}；每类房间目标保留 ${audit.candidate_retain_target_per_room_type} 个组合；阶段技能分别按 A ${audit.modeled_shift_hours}h / B ${audit.modeled_shift_hours_b || audit.modeled_shift_hours}h 积分${audit.duration_refinements?`（经 ${audit.duration_refinements} 次时长回代）`:""}；${audit.rotation_strategy}。目标：${objective?.label || "按布局产出"}；硬约束：${objective?.hard_constraints || "使用页面布局"}${objective?.mode === "sanity_value" && valuation ? `；${valuation.note}` : ""}。` : "";
  $("warnings").innerHTML = [objectiveAudit,searchWarning,...data.warnings].filter(Boolean).map(x => `<div class="warning">${escapeHtml(x)}</div>`).join("");
  renderMorale(data.morale, data.rotation);
  const teams = data.rotation?.teams || {A:{support_rooms:data.support_rooms||[],rooms:data.rooms}};
  const workHours=data.rotation?.team_work_hours||{};
  const cycleHours=Object.values(workHours).reduce((sum,value)=>sum+(+value||0),0)||24;
  $("rooms").innerHTML = Object.entries(teams).map(([team,plan])=>{
    const share=(+workHours[team]||cycleHours)/cycleHours, tm=plan.metrics||{};
    const teamSummary=`<div class="team-cycle-summary"><div><span>周期占比</span><strong>${(share*100).toFixed(1)}%</strong><small>${workHours[team]||cycleHours}h / ${cycleHours}h</small></div><div><span>对图表龙门币贡献</span><strong>${number(Math.round((+tm.lmd_per_day||0)*share))}</strong><small>本队满日等效 ${number(Math.round(+tm.lmd_per_day||0))}</small></div><div><span>对图表经验贡献</span><strong>${number(Math.round((+tm.exp_per_day||0)*share))}</strong><small>本队满日等效 ${number(Math.round(+tm.exp_per_day||0))}</small></div><div><span>对图表赤金净流贡献</span><strong>${signed((+tm.gold_net_per_day||0)*share)}</strong><small>本队满日等效 ${signed(+tm.gold_net_per_day||0)}</small></div></div>`;
    return `<section class="team-room-group"><div class="team-room-title"><strong>${team} 队</strong><span>${workHours[team] ? `每循环工作 ${workHours[team]} 小时` : "单班方案"}</span></div>${teamSummary}<div class="rooms">${[...(plan.support_rooms||[]),...(plan.rooms||[])].map(room => {
    const event=(data.rotation?.rooms||[]).find(row=>row.room===room.room)?.events?.find(item=>item.team===team);
    const rates=event ? Object.values(event.morale_rates||{}).map(Number) : [];
    const rateRange=rates.length ? `${Math.min(...rates)}${Math.max(...rates)!==Math.min(...rates)?`–${Math.max(...rates)}`:""}` : "—";
    const output=roomOutput(room), totalEfficiency=room.key==="power" ? 5+(+room.efficiency||0) : (room.multiplier ? (+room.multiplier-1)*100 : null);
    return `
    <article class="room">
      <div class="room-head"><h3>${escapeHtml(room.room)}</h3><span class="eff">${totalEfficiency==null?`技能 +${room.efficiency}%`:`实际 +${totalEfficiency.toFixed(2)}%`}</span></div>
      <div class="names">${room.names.map(escapeHtml).join(" · ")}</div>
      ${output?`<div class="room-output"><span>本队在岗时日产等效</span><strong>${escapeHtml(output)}</strong><small>折算到上方 24h 图表：${escapeHtml(roomOutput(room,share))}</small></div>`:""}
      ${totalEfficiency!=null?`<div class="eff-ledger"><span>技能/状态加成 +${room.efficiency}%</span><span>${room.key==="power"?"发电站在岗基础 +5%":`${room.names.length} 名在岗基础 +${room.names.length}%`}</span><span>${room.key==="power"?`充能增幅 +${totalEfficiency.toFixed(2)}%`:`生产倍率 ×${(+room.multiplier).toFixed(4)}`}</span></div>`:""}
      <div class="skills">${room.details.map(d => `${escapeHtml(d.operator)}：${d.skills.map(s => escapeHtml(s.name)).join(" / ") || "无对应技能"}`).join("<br>")}</div>
      ${(room.mechanic_notes || []).length ? `<div class="skills">机制：${room.mechanic_notes.map(escapeHtml).join("；")}</div>` : ""}
      ${event ? `<div class="endurance"><span>实际在岗 ${event.scheduled_work_hours}h</span><span>本组合安全上限 ${event.safe_work_hours}h</span><span>心情消耗 ${rateRange}/h</span></div>` : ""}
      ${room.group ? `<span class="confidence">${escapeHtml(room.group)} · MAA 组合候选</span>` : `<span class="confidence">${room.confidence === "direct" ? "直接数值模型" : room.confidence === "state_model" ? "跨设施状态模型" : "保守估算"}</span>`}
    </article>`}).join("")}</div></section>`;
  }).join("");
  runQuickSimulation(data);
  $("results").scrollIntoView({behavior:"smooth", block:"start"});
}

function roomOutput(room,scale=1) {
  const n=value=>number(Math.round((+value||0)*scale));
  if(room.key==="trade"&&room.trade) return `${n(room.trade.lmd_per_day)} 龙门币 / ${(+room.trade.gold_per_day*scale).toFixed(2)} 赤金消耗`;
  if(room.key==="gold") return `${(20*(+room.multiplier||0)*scale).toFixed(2)} 赤金`;
  if(room.key==="exp") return `${n(8000*(+room.multiplier||0))} EXP`;
  if(room.key==="shard") return `${(24*(+room.multiplier||0)*scale).toFixed(2)} 源石碎片`;
  if(room.key==="orundum"&&room.orundum) return `${n(room.orundum.orundum_per_day)} 合成玉 / ${(+room.orundum.shards_per_day*scale).toFixed(2)} 碎片消耗`;
  if(room.key==="power") return `${(240*(5+(+room.efficiency||0))/100*scale).toFixed(2)} 架无人机增量`;
  return "";
}

function renderObjectiveComparison(objective,currentMetrics) {
  const comparison=objective?.comparison;
  if(!comparison){$("objectiveComparison").classList.add("hidden");return;}
  $("objectiveComparison").classList.remove("hidden");
  const alt=comparison.alternate_metrics||{}, deltas=comparison.metric_deltas_alternate_minus_current||{};
  const differences=comparison.room_differences||[];
  const converged=!!comparison.selected_dominates_alternate;
  const metric=(label,current,alternate,key)=>`<div><span>${label}</span><strong>${number(Math.round(+current||0))}</strong><small>备选 ${number(Math.round(+alternate||0))} · 差 ${signed(deltas[key]||0,3)}</small></div>`;
  $("objectiveComparison").innerHTML=`<div class="comparison-head"><div><p class="eyebrow">OBJECTIVE CROSS-CHECK</p><h3>目标函数交叉审计</h3></div><span class="comparison-state ${converged?"same":"different"}">${converged?"两目标最终收敛":"目标产生取舍"}</span></div>
    <p class="comparison-copy">当前：<b>${escapeHtml(objective.label)}</b>；同一 Box 完整重算：<b>${escapeHtml(comparison.alternate_label)}</b>。${converged?"当前完整排班在布局分数和等效理智分数上都不低于另一候选，因此两种目标会合法地返回同一方案；下方列出被淘汰候选的细微差别。":"两种完整排班分别在不同评分上占优，所以切换目标会改变最终方案。"}${comparison.cross_candidate_reranked?" 本次还纠正了顺序生成 A/B 后的候选反转。":""}</p>
    <div class="comparison-metrics">${metric("龙门币 / 日",currentMetrics.lmd_per_day,alt.lmd_per_day,"lmd_per_day")}${metric("经验 / 日",currentMetrics.exp_per_day,alt.exp_per_day,"exp_per_day")}${metric("赤金制造 / 日",currentMetrics.gold_made_per_day,alt.gold_made_per_day,"gold_made_per_day")}${metric("赤金净流 / 日",currentMetrics.gold_net_per_day,alt.gold_net_per_day,"gold_net_per_day")}</div>
    <div class="room-differences">${differences.map(row=>`<div><strong>${row.team} 班 · ${escapeHtml(row.room_type)}</strong><p><span>当前</span>${row.current.map(group=>escapeHtml(group.join(" / "))).join("；")}</p><p><span>备选</span>${row.alternate.map(group=>escapeHtml(group.join(" / "))).join("；")}</p></div>`).join("")||'<p class="side-note">忽略同类房间编号互换后，两套目标在当前 Box 得到相同组合；这表示本次候选收敛，不表示两个公式相同。</p>'}</div>`;
}

function signed(value, digits = 2) {
  const rounded = Number(value || 0).toFixed(digits).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
  return `${+value >= 0 ? "+" : ""}${rounded}`;
}

function renderProductionMonitor(m) {
  const rows = [
    {kind:"lmd", icon:"龙", name:"龙门币", total:m.lmd_per_day, unit:"/ 日", rate:m.lmd_per_day/24, note:"贸易订单兑现"},
    {kind:"exp", icon:"EXP", name:"作战经验", total:m.exp_per_day, unit:"/ 日", rate:m.exp_per_day/24, note:"作战记录制造"},
    {kind:"gold", icon:"Au", name:"赤金制造", total:m.gold_made_per_day, unit:"根 / 日", rate:m.gold_made_per_day/24, note:`贸易站消耗 ${m.gold_used_per_day} 根 / 日`},
    {kind:"drone", icon:"⚡", name:"无人机", total:m.drones_per_day, unit:"架 / 日", rate:m.drones_per_day/24, note:m.drone_target},
  ];
  if (m.orundum_per_day > 0) rows.splice(2,0,{kind:"orundum",icon:"玉",name:"合成玉",total:m.orundum_per_day,unit:"/ 日",rate:m.orundum_per_day/24,note:`碎片净流 ${signed(m.shards_net_per_day)} / 日`});
  $("productionMonitor").innerHTML = rows.map(row => `<div class="machine-row ${row.kind}">
    <span class="machine-icon">${row.icon}</span>
    <div class="machine-copy"><strong>${row.name}</strong><small>${escapeHtml(row.note)}</small></div>
    <div class="machine-rate"><strong>${number(Math.round(row.total))}</strong><span>${row.unit}</span><small>${number(Math.round(row.rate))} / 小时</small></div>
    <i class="machine-pulse"></i>
  </div>`).join("");
}

function renderGoldMonitor(m) {
  const net = m.gold_net_per_day;
  let forecast = "库存稳定或增长";
  if (net < 0 && m.gold_inventory_days != null && m.gold_inventory > 0) forecast = `约 ${m.gold_inventory_days} 天后耗尽`;
  else if (net < 0) forecast = "填写库存后可预测耗尽时间";
  $("goldMonitor").innerHTML = `
    <div class="flow-ledger">
      <div><span>制造站</span><strong class="positive">+${m.gold_made_per_day}</strong></div>
      <div><span>任务 / 活动折算</span><strong class="positive">+${m.gold_external_per_day}</strong></div>
      <div><span>贸易站消耗</span><strong class="negative">−${m.gold_used_per_day}</strong></div>
    </div>
    <div class="net-flow ${net < 0 ? "draining" : "growing"}"><span>库存速度</span><strong>${signed(net)} / 日</strong><small>${forecast}</small></div>
    <div class="stock-line"><span>当前库存</span><strong>${number(m.gold_inventory || 0)} 根</strong></div>
    <p class="side-note">站内制造净流量 ${signed(m.gold_production_net_per_day)} / 日。赤金仅作为贸易中间品，负数本身不是低效。</p>`;
}

function renderDroneMonitor(m) {
  const effect=m.drone_effect||{};
  const allocations=(effect.allocations||[]).filter(item=>(+item.drones_per_day||0)>0.001);
  const contributions=[
    ["龙门币",effect.lmd_per_day], ["作战经验",effect.exp_per_day],
    ["赤金制造",effect.gold_made_per_day], ["赤金消耗",effect.gold_used_per_day],
    ["合成玉",effect.orundum_per_day], ["碎片制造",effect.shards_made_per_day],
  ].filter(([,value])=>Math.abs(+value||0)>1e-6);
  $("droneMonitor").innerHTML=`<div class="flow-ledger">
    <div><span>基础恢复</span><strong>240 架 / 日</strong></div>
    <div><span>发电站增幅</span><strong class="positive">+${m.power_bonus}%</strong></div>
    <div><span>理论恢复能力</span><strong>${m.drones_recovery_potential_per_day ?? m.drones_per_day} 架 / 日</strong></div>
    <div><span>实际可用于加速</span><strong>${m.drones_per_day} 架 / 日</strong></div>
    <div><span>${m.drone_capacity || 235} 架容量溢出</span><strong class="${(+m.drone_overflow_lost_per_day||0)>0?"negative":"positive"}">${m.drone_overflow_lost_per_day || 0} 架 / 日</strong></div>
    <div><span>等效加速</span><strong>${effect.equivalent_hours ?? m.drone_hours_per_day} 小时 / 日</strong></div>
  </div><div class="drone-target"><span>收取时的实际分流</span><strong>${escapeHtml(effect.target||m.drone_target||"未使用")}</strong></div>
  <div class="drone-routes">${allocations.map(item=>`<div><span><b>${escapeHtml(item.team?`${item.team} 班 · `:"")}${escapeHtml(item.label||item.kind)}</b><small>${escapeHtml(item.target||"")}</small></span><strong>${number(Math.round(+item.drones_per_day||0))} 架<small>${(+item.fraction*100||0).toFixed(1)}%</small></strong></div>`).join("")||'<p class="side-note">没有无人机投入。</p>'}</div>
  <div class="drone-deltas">${contributions.map(([label,value])=>`<p><span>${label}</span><strong>${signed(value,3)} / 日</strong></p>`).join("")||'<p><span>当前设置不把无人机计入产出</span></p>'}</div>
  ${effect.balance?`<p class="constraint ${effect.balance.reachable?"ok":"warn"}">自动瓶颈：${effect.balance.bottleneck==="gold"?"赤金供给":"贸易兑现"} · 用户允许 ${signed(effect.balance.target_gold_net_per_day)}/日 · 可达区间 ${signed(effect.balance.all_trade_gold_net_per_day)} ～ ${signed(effect.balance.all_gold_gold_net_per_day)}/日 · 分流后 ${signed(effect.balance.projected_gold_net_per_day)}/日 · ${effect.balance.binding?"目标正在约束分流":effect.balance.regime==="trade_saturated"?"目标未生效：已 100% 投贸易，再放宽不会增加收益":effect.balance.reachable?"混合班次中部分目标未生效":"即使全投赤金仍不可达"}</p>`:""}
  <p class="side-note">无人机先恢复进库存，达到 ${m.drone_capacity || 235} 架后暂停恢复，只在下方标出的收取节点投入；解析曲线在节点跳变，随机模拟重放相同分流。</p>`;
}

function renderCrossRoomFlows(flows) {
  if (!flows.length) {
    $("crossRoomPanel").innerHTML = '<p class="side-note">当前组合没有触发已建模的跨房间生产状态。</p>';
    return;
  }
  $("crossRoomPanel").innerHTML = flows.map(flow => `<details class="state-flow ${flow.active === false ? "inactive" : ""}" open>
    <summary><span><i></i>${escapeHtml(flow.label)}</span><strong>${number(flow.value)} ${escapeHtml(flow.unit)}</strong></summary>
    <div class="state-source"><small>来源</small>${flow.sources.map(s => `<p><b>${escapeHtml(s.name)}</b><span>${escapeHtml(s.detail)}</span></p>`).join("")}</div>
    <div class="state-arrow">↓</div>
    <div class="state-consumers"><small>${flow.consumers.length ? "实际受益" : "当前未转化为产出"}</small>${flow.consumers.map(c => `<p><b>${escapeHtml(c.room)} <em>+${c.contribution_percent}%</em></b><span>${escapeHtml(c.detail)} · ${c.operators.map(escapeHtml).join(" / ")}</span>${c.output_unit ? `<mark>本房间折算 +${number(Math.round(c.output_delta_per_day))} ${escapeHtml(c.output_unit)}</mark>` : ""}</p>`).join("") || '<p><span>没有对应体系干员进入生产设施，因此贡献为 0。</span></p>'}</div>
  </details>`).join("");
}

function hourLabel(hour) {
  const day=Math.floor(hour/24)+1, within=hour%24;
  return `D${day} ${String(Math.floor(within)).padStart(2,"0")}:00`;
}

function renderRotation(rotation) {
  if (!rotation) {
    $("rotationPattern").textContent="未生成第二队";
    $("shiftStrip").innerHTML="";
    $("operatorTimeline").innerHTML='<p class="side-note">当前 Box 不足以生成两套互斥班组。</p>';
    return;
  }
  const durationText=Object.entries(rotation.team_work_hours||{}).map(([team,h])=>`${team} ${h}h`).join(" / ");
  $("rotationPattern").textContent=`${durationText || rotation.pattern.join(" → ")} · 循环 ${rotation.natural_cycle_hours || rotation.cycle_hours}h · 收取 ${rotation.collection_interval_hours || rotation.shift_hours}h`;
  $("shiftStrip").innerHTML=rotation.shifts.map(shift=>`<details class="shift-chip team-${shift.team.toLowerCase()}">
    <summary><strong>第 ${shift.index} 班 · ${shift.team} 队</strong><span>${hourLabel(shift.start)}–${hourLabel(shift.end)}</span></summary>
    <div>${shift.rooms.map(room=>`<p><b>${escapeHtml(room.room)}</b><span>${room.names.map(escapeHtml).join(" / ")}</span>${room.time_profiles.map(profile=>`<em>${escapeHtml(profile.operator)} ${escapeHtml(profile.label)}：班均 +${profile.average_percent}%</em>`).join("")}</p>`).join("")}</div>
  </details>`).join("");
  const axisStep=rotation.collection_interval_hours || 4;
  const tickCount=Math.floor(rotation.cycle_hours/axisStep);
  const ticks=Array.from({length:tickCount+1},(_,i)=>`<span style="left:${i*axisStep/rotation.cycle_hours*100}%">${i*axisStep}h</span>`).join("");
  const collectionLines=Array.from({length:tickCount-1},(_,i)=>`<i class="collection-line" style="left:${(i+1)*axisStep/rotation.cycle_hours*100}%" title="${(i+1)*axisStep}h 统一收取"></i>`).join("");
  const rows=(rotation.rooms||[]).map(room=>`<div class="timeline-row room-timeline-row">
    <strong title="${escapeHtml(room.room)}">${escapeHtml(room.room)}</strong>
    <div class="timeline-lane">${collectionLines}${room.events.map(event=>{
      const left=event.start/rotation.cycle_hours*100, width=(event.end-event.start)/rotation.cycle_hours*100;
      const skills=(event.details||[]).map(d=>`${d.operator}：${(d.skills||[]).map(s=>s.name).join("/")||"无对应技能"}`).join("；");
      const phases=(event.time_profiles||[]).map(p=>`${p.operator} ${p.label} 班均+${p.average_percent}%`).join("；");
      const title=`${hourLabel(event.start)}–${hourLabel(event.end)} · ${event.team} 班 · 实际 ${event.scheduled_work_hours}h / 本组合安全上限 ${event.safe_work_hours}h · 效率 +${event.efficiency}% · 最低结束心情 ${event.morale_min_end} · ${event.names.join(" / ")}${skills?` · ${skills}`:""}${phases?` · ${phases}`:""}`;
      return `<i class="timeline-event room-event work-${event.team.toLowerCase()}" style="left:${left}%;width:${width}%" title="${escapeHtml(title)}"><span class="room-team">${event.team}</span><span class="operator-chips">${event.names.map(name=>`<b>${escapeHtml(name)}</b>`).join("")}</span></i>`;
    }).join("")}</div>
  </div>`).join("");
  const inventoryNote=rotation.inventory_policy?.note || "";
  const dormNote=rotation.dormitory?.note || "";
  const droneEvents=rotation.production_curve?.drone_events||[];
  const eventLedger=droneEvents.length?`<div class="drone-event-ledger"><strong>无人机收取/投入事件</strong>${droneEvents.map(event=>`<span><b>${event.minute/60}h · ${event.team}班 · ${number(Math.round(event.drones_spent))} 架</b>${(event.targets||[]).map(target=>`${escapeHtml(target.label)} ${number(Math.round(target.drones))}`).join(" / ")||"保留"}</span>`).join("")}</div>`:"";
  $("operatorTimeline").innerHTML=`<div class="timeline-axis"><strong>房间</strong><div>${ticks}</div></div>${rows}${eventLedger}<p class="timeline-note">${escapeHtml(rotation.morale.note)} 排程校验：${rotation.morale.feasible ? "两队均可在下次上班前恢复" : "存在恢复时间或床位小时不足"}。${escapeHtml(dormNote)} ${escapeHtml(inventoryNote)} 悬停班次查看干员、技能、效率与结束心情。</p>`;
}

const curveLabels={lmd_per_day:"龙门币",exp_per_day:"作战经验",gold_net_per_day:"赤金净流量",gold_made_per_day:"赤金制造",gold_used_per_day:"赤金消耗",orundum_per_day:"合成玉",drones_per_day:"无人机库存"};

function combinedCurveSvg(points,key,label,events) {
  const width=980,height=330,pad={l:72,r:72,t:48,b:42};
  const cumulative=points.map(point=>+point.cumulative[key]||0), rates=points.map(point=>+point.rates_per_hour[key]||0);
  const domain=values=>{let min=Math.min(0,...values),max=Math.max(0,...values);if(Math.abs(max-min)<1e-9)max=min+1;return [min,max]};
  const [cmin,cmax]=domain(cumulative),[rmin,rmax]=domain(rates);
  const x=minute=>pad.l+minute/1440*(width-pad.l-pad.r);
  const scale=(value,min,max)=>height-pad.b-(value-min)/(max-min)*(height-pad.t-pad.b);
  const cy=value=>scale(value,cmin,cmax),ry=value=>scale(value,rmin,rmax);
  const line=(field,y)=>points.map(point=>`${x(point.minute).toFixed(2)},${y(+point[field][key]||0).toFixed(2)}`).join(" ");
  const ticks=[0,4,8,12,16,20,24].map(hour=>`<g><line x1="${x(hour*60)}" y1="${pad.t}" x2="${x(hour*60)}" y2="${height-pad.b}" class="curve-grid-line"/><text x="${x(hour*60)}" y="${height-14}" text-anchor="middle">${hour}h</text></g>`).join("");
  const markers=(events||[]).map(event=>{const title=`${Math.floor(event.minute/60)}h 收取 · ${event.team} 班 · 投入 ${event.drones_spent} 架 · ${(event.targets||[]).map(t=>`${t.label} ${t.drones}`).join(" / ")}`;return `<g class="drone-marker"><line x1="${x(event.minute)}" y1="${pad.t}" x2="${x(event.minute)}" y2="${height-pad.b}"/><circle cx="${x(event.minute)}" cy="${cy(points.find(p=>p.minute===event.minute)?.cumulative[key]||0)}" r="5"><title>${escapeHtml(title)}</title></circle></g>`}).join("");
  const cumulativeLabel=key==="drones_per_day" ? "当前库存（左轴）" : `累计 ${label}（左轴）`;
  return `<svg class="combined-curve" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(label)}累计与实时速率">
    ${ticks}<line x1="${pad.l}" y1="${cy(0)}" x2="${width-pad.r}" y2="${cy(0)}" class="curve-zero"/>${markers}
    <polyline points="${line("cumulative",cy)}" class="curve-cumulative" vector-effect="non-scaling-stroke"/>
    <polyline points="${line("rates_per_hour",ry)}" class="curve-rate" vector-effect="non-scaling-stroke"/>
    <text x="${pad.l-10}" y="${pad.t+3}" text-anchor="end">${number(Math.round(cmax))}</text><text x="${pad.l-10}" y="${height-pad.b}" text-anchor="end">${number(Math.round(cmin))}</text>
    <text x="${width-pad.r+10}" y="${pad.t+3}">${number(Math.round(rmax))}/h</text><text x="${width-pad.r+10}" y="${height-pad.b}">${number(Math.round(rmin))}/h</text>
    <g class="curve-legend"><line x1="${pad.l}" y1="22" x2="${pad.l+24}" y2="22" class="curve-cumulative"/><text x="${pad.l+31}" y="26">${escapeHtml(cumulativeLabel)}</text><line x1="${pad.l+230}" y1="22" x2="${pad.l+254}" y2="22" class="curve-rate"/><text x="${pad.l+261}" y="26">实时速率 / 小时（右轴）</text><circle cx="${pad.l+474}" cy="22" r="4" class="legend-drone"/><text x="${pad.l+485}" y="26">无人机投入节点</text></g>
  </svg>`;
}

function renderYieldCurve(curve) {
  if (!curve?.points?.length) {
    $("yieldCurve").innerHTML='<p class="side-note">生成轮班后显示 24 小时收益曲线。</p>';
    return;
  }
  const key=$("curveMetric").value;
  const label=curveLabels[key]||key;
  const points=curve.points;
  const final=+points.at(-1).cumulative[key]||0;
  const rates=points.map(point=>+point.rates_per_hour[key]||0);
  const transitions=points.filter((point,index)=>index===0||point.team!==points[index-1].team)
    .map(point=>`${Math.floor(point.minute/60)}:${String(point.minute%60).padStart(2,"0")} ${point.team}班`).join(" → ");
  const hours=state.lastResult?.rotation?.team_work_hours||{}, cycle=Object.values(hours).reduce((sum,value)=>sum+(+value||0),0);
  const weighting=Object.entries(hours).map(([team,value])=>`${team} ${value}h`).join(" + ");
  $("yieldCurve").innerHTML=`<div class="curve-summary"><div><span>${key==="drones_per_day"?"24h 末库存":"24h 累计"}</span><strong>${signed(final)} ${escapeHtml(label)}</strong></div><div><span>${key==="drones_per_day"?"恢复速率范围":"小时速率范围"}</span><strong>${signed(Math.min(...rates))} ～ ${signed(Math.max(...rates))}</strong><small>每分钟 ${signed(Math.min(...rates)/60,3)} ～ ${signed(Math.max(...rates)/60,3)}</small></div><div><span>班次切换</span><strong>${escapeHtml(transitions)}</strong></div><div><span>与设施卡片统一口径</span><strong>${escapeHtml(weighting||"单班")}</strong><small>${cycle?`按 ${cycle}h 循环折算到 24h`:`直接使用单班日产`}</small></div></div>
    ${combinedCurveSvg(points,key,label,curve.drone_events)}<p class="side-note">${escapeHtml(curve.note)}</p>`;
}

$("curveMetric").addEventListener("change",()=>renderYieldCurve(state.lastResult?.rotation?.production_curve));

async function simulateSchedule(result, days, trials) {
  const plans=result.rotation ? Object.values(result.rotation.teams) : [{rooms:result.rooms,metrics:result.metrics}];
  const samples=await Promise.all(plans.map(plan=>request("/api/simulate", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({rooms:plan.rooms, metrics:plan.metrics, days, trials})})));
  if(samples.length===1) return samples[0];
  const expected=result.rotation.average_metrics;
  const durations=result.rotation.team_work_hours||{A:1,B:1};
  const weights=[durations.A||1,durations.B||1], weightTotal=weights[0]+weights[1];
  const keys=["lmd_per_day","lmd_p05","lmd_p95","exp_per_day","gold_made_per_day","gold_used_per_day","gold_net_per_day","orundum_per_day","shards_made_per_day","shards_used_per_day","shards_net_per_day"];
  const simulated={}; keys.forEach(key=>simulated[key]=samples.reduce((sum,x,index)=>sum+(+x.simulated[key]||0)*weights[index],0)/weightTotal);
  const sample_run={}; ["lmd_per_day","gold_used_per_day","gold_net_per_day"].forEach(key=>sample_run[key]=samples.reduce((sum,x,index)=>sum+(+x.sample_run[key]||0)*weights[index],0)/weightTotal);
  const difference_percent={}; ["lmd_per_day","exp_per_day","gold_made_per_day","gold_used_per_day","orundum_per_day","shards_made_per_day","shards_used_per_day"].forEach(key=>difference_percent[key]=expected[key]?((simulated[key]-expected[key])/Math.abs(expected[key])*100):null);
  return {days,trials,simulated,sample_run,seed:samples.map(x=>x.seed).join(" / "),expected,difference_percent,assumptions:[`A/B 两套队伍分别模拟后按在岗时长 ${weights[0]}:${weights[1]} 合并。`,...samples[0].assumptions]};
}

async function runQuickSimulation(result) {
  const sequence = ++state.quickSimSequence;
  $("quickSimulation").innerHTML = '<div class="sim-loading"><i></i><span>正在快进 30 天 × 300 次…</span></div>';
  try {
    const data=await simulateSchedule(result,30,300);
    if (sequence !== state.quickSimSequence) return;
    const d=data.difference_percent, s=data.simulated;
    $("quickSimulation").innerHTML = `<div class="quick-grid">
      <div><span>模拟龙门币</span><strong>${number(Math.round(s.lmd_per_day))}</strong><small>${signed(d.lmd_per_day,3)}%</small></div>
      <div><span>模拟赤金净流</span><strong>${signed(s.gold_net_per_day)}</strong><small>根 / 日</small></div>
    </div><p class="convergence ${Math.abs(d.lmd_per_day || 0) < 1 ? "ok" : "warn"}">${Math.abs(d.lmd_per_day || 0) < 1 ? "✓ 多次随机试验的均值已收敛" : "△ 与解析期望存在可见偏差"}</p><p class="side-note">本次第 1 条随机轨迹：龙门币 ${number(Math.round(data.sample_run?.lmd_per_day||0))}/日，赤金净流 ${signed(data.sample_run?.gold_net_per_day||0)}/日；随机种子 ${escapeHtml(data.seed)}。再次运行会生成新订单序列。均值的 90% 区间 ${number(Math.round(s.lmd_p05))}–${number(Math.round(s.lmd_p95))}。</p>`;
  } catch (error) {
    if (sequence === state.quickSimSequence) $("quickSimulation").innerHTML = `<p class="side-note error-copy">模拟失败：${escapeHtml(error.message)}</p>`;
  }
}

function renderMorale(m, rotation) {
  const helpers = (m.dorm_helpers || []).slice(0,4).map(x=>`${escapeHtml(x.operator)}（全体 +${x.all} / 单体 +${x.single}）`).join("、") || "当前 Box 无需专门配置";
  const locked=rotation?.dormitory?.locked_helper;
  const fiammetta=rotation?.dormitory?.fiammetta;
  const fiammettaAudit=rotation?.morale?.fiammetta;
  const rotationAudits=Object.entries(rotation?.morale?.teams||{});
  const slowest=rotationAudits.length ? Math.max(...rotationAudits.map(([,audit])=>+audit.slowest_recovery_hours||0)) : m.max_recovery_hours;
  const bedLedger=rotationAudits.length ? rotationAudits.map(([team,audit])=>`${team} ${audit.bed_hours_required}/${audit.bed_hours_available}`).join(" · ") : `${m.bed_hours_required} / ${m.bed_hours_available}`;
  const sustainable=rotation?.morale?.feasible ?? m.two_team_feasible;
  $("moraleAudit").innerHTML = `<h3>轮班与宿舍可持续性</h3><div class="morale-grid">
    <div><span>满级宿舍基础恢复</span><strong>${rotation?.morale?.base_recovery_per_hour || m.base_recovery_per_hour} / 小时</strong></div>
    <div><span>两班最慢回满</span><strong>${slowest} 小时</strong></div>
    <div><span>A/B 所需 / 可用床位小时</span><strong>${bedLedger}</strong></div>
    <div><span>当前循环</span><strong>${sustainable ? "两队可持续" : "恢复不足"}</strong></div>
  </div><p>${escapeHtml(rotation?.morale?.note || m.note)} 含 ${m.production_slots} 个产出岗位与 ${m.support_slots} 个辅助岗位；${m.owned_operators} 名干员相对最低 ${m.minimum_distinct_operators} 名的容量判断：${m.roster_capacity_ok ? "通过" : "不足"}。</p><p>固定宿舍位：${locked ? `${escapeHtml(locked.name)}（群体 +${locked.all}/小时）` : "未启用"}。菲亚梅塔：${fiammetta?.active ? `恢复 ${escapeHtml(fiammetta.target_operator_name)}；A→B 后回满 ${fiammettaAudit.recover_during_b_hours}h，B→A 后回满 ${fiammettaAudit.recover_during_a_hours}h` : escapeHtml(fiammetta?.note || (m.fiammetta_owned ? "已拥有但本次未激活" : "机制支持，当前未拥有"))}。可用宿舍辅助前列：${helpers}</p>`;
}

$("simulateButton").addEventListener("click", async () => {
  if (!state.lastResult) return message("simulateMessage", "请先计算一份推荐方案。", true);
  const button = $("simulateButton"); button.disabled = true; button.textContent = "正在快进…";
  hideMessage("simulateMessage");
  try {
    const data = await simulateSchedule(state.lastResult,+$("simDays").value,+$("simTrials").value);
    renderSimulation(data);
  } catch (error) { message("simulateMessage", error.message, true); }
  finally { button.disabled = false; button.textContent = "开始快进模拟"; }
});

function renderSimulation(data) {
  const s=data.simulated, d=data.difference_percent;
  const card=(label,value,key,extra="")=>`<article><span>${label}</span><strong>${value}</strong><small>相对解析期望 ${d[key] == null ? "—" : `${d[key] >= 0 ? "+" : ""}${d[key]}%`}</small>${extra}</article>`;
  $("simulationResult").innerHTML =
    card("龙门币 / 日", number(Math.round(s.lmd_per_day)), "lmd_per_day", `<span>90% 区间 ${number(Math.round(s.lmd_p05))}–${number(Math.round(s.lmd_p95))}</span>`) +
    card("经验 / 日", number(Math.round(s.exp_per_day)), "exp_per_day") +
    card("赤金制造 / 日", s.gold_made_per_day, "gold_made_per_day") +
    card("赤金消耗 / 日", s.gold_used_per_day, "gold_used_per_day") +
    (s.orundum_per_day > 0 ? card("合成玉 / 日", Math.round(s.orundum_per_day), "orundum_per_day") + card("碎片净变化 / 日", signed(s.shards_net_per_day), "shards_made_per_day") : "") +
    `<p class="simulation-notes">本轮第 1 条轨迹：龙门币 ${number(Math.round(data.sample_run?.lmd_per_day||0))}/日，赤金净流 ${signed(data.sample_run?.gold_net_per_day||0)}/日；随机种子 ${escapeHtml(data.seed)}。快进 ${data.days} 天 × ${number(data.trials)} 次。${data.assumptions.map(escapeHtml).join(" ")}</p>`;
  $("simulationResult").classList.remove("hidden");
}

function renderBars(m) {
  const values = [
    ["龙门币", m.lmd_per_day, ""], ["作战经验", m.exp_per_day, "blue"],
    ["赤金制造 ×500", m.gold_made_per_day * 500, "gold"], ["赤金消耗 ×500", m.gold_used_per_day * 500, "red"]
  ];
  if(m.orundum_per_day>0) values.push(["合成玉 ×100",m.orundum_per_day*100,"blue"]);
  const max = Math.max(...values.map(x => x[1]));
  $("barChart").innerHTML = values.map(([label,value,kind]) => `<div class="bar-row"><span>${label}</span><div class="bar-track"><div class="bar ${kind}" style="width:${value/max*100}%"></div></div><strong>${number(Math.round(value))}</strong></div>`).join("") + `<p class="skills">无人机投向：${escapeHtml(m.drone_target)}；等效加速 ${m.drone_hours_per_day} 小时/日。</p>`;
}

function renderPareto(points) {
  const svg = $("paretoChart");
  if (!points.length) { svg.innerHTML = '<text x="20" y="40">没有可区分的权重方案</text>'; return; }
  const pad = {l:62,r:24,t:20,b:44}, width=620, height=300;
  const xs = points.map(p=>p.lmd_per_day), ys=points.map(p=>p.exp_per_day);
  let xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys);
  if (xmin===xmax){xmin*=.95;xmax*=1.05} if(ymin===ymax){ymin*=.95;ymax*=1.05}
  const x=v=>pad.l+(v-xmin)/(xmax-xmin)*(width-pad.l-pad.r), y=v=>height-pad.b-(v-ymin)/(ymax-ymin)*(height-pad.t-pad.b);
  const sorted=[...points].sort((a,b)=>a.lmd_per_day-b.lmd_per_day);
  svg.innerHTML=`<line class="axis" x1="${pad.l}" y1="${height-pad.b}" x2="${width-pad.r}" y2="${height-pad.b}"/><line class="axis" x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height-pad.b}"/>
    <text x="${width/2-30}" y="292">龙门币 / 日</text><text transform="translate(15 185) rotate(-90)">经验 / 日</text>
    <text x="${pad.l}" y="278">${number(xmin)}</text><text x="${width-pad.r-50}" y="278">${number(xmax)}</text>
    <text x="18" y="${height-pad.b}">${number(ymin)}</text><text x="18" y="${pad.t+5}">${number(ymax)}</text>
    <polyline class="line" points="${sorted.map(p=>`${x(p.lmd_per_day)},${y(p.exp_per_day)}`).join(" ")}"/>
    ${points.map(p=>`<circle class="point" cx="${x(p.lmd_per_day)}" cy="${y(p.exp_per_day)}" r="7"><title>龙门币 ${p.lmd_per_day}，经验 ${p.exp_per_day}，赤金净变化 ${p.gold_net_per_day}</title></circle>`).join("")}`;
}

loadCatalog().catch(error => { $("catalogStatus").textContent = `载入失败：${error.message}`; });
