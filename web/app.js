const state = { catalog: [], byName: new Map(), roster: [], scanId: null, scanPoll: null, lastResult: null, quickSimSequence: 0, charts: { yield: null, bars: null } };
const $ = (id) => document.getElementById(id);

function setTheme(theme) {
  document.documentElement.dataset.theme=theme;
  localStorage.setItem("maaBaseTheme",theme);
  $("themeToggle").textContent=theme==="light" ? "◐ 深色" : "☀︎ 浅色";
  if (state.lastResult) requestAnimationFrame(() => {
    renderYieldCurve(state.lastResult?.rotation?.production_curve);
    renderBars(state.lastResult?.rotation?.average_metrics || state.lastResult?.metrics || {});
  });
}
setTheme(localStorage.getItem("maaBaseTheme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
$("themeToggle").addEventListener("click",()=>setTheme(document.documentElement.dataset.theme==="light" ? "dark" : "light"));

function selectResultTab(name) {
  document.querySelectorAll("[data-result-tab]").forEach(button => button.classList.toggle("active", button.dataset.resultTab === name));
  document.querySelectorAll("[data-tab-panel]").forEach(panel => panel.classList.toggle("active", panel.dataset.tabPanel === name));
  requestAnimationFrame(() => Object.values(state.charts).forEach(chart => chart?.resize()));
}
document.querySelectorAll("[data-result-tab]").forEach(button => button.addEventListener("click", () => selectResultTab(button.dataset.resultTab)));

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
  const ownedFiammetta=BaseView.fiammettaOwned(state.roster);
  $("fiammettaOption").hidden=!ownedFiammetta;
  $("enableFiammetta").disabled=!ownedFiammetta;
  const sorted=BaseView.sortOperators(state.roster,new Map(state.catalog.map(op=>[op.id,op])));
  $("rosterPreview").innerHTML=sorted.slice(0,5).map(op=>operatorAvatar(op.id,op.name,'preview-avatar')).join('') || '<span>＋</span>';
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
function operatorAvatar(id, name, className="operator-avatar") {
  const source=`https://torappu.prts.wiki/assets/char_avatar/${encodeURIComponent(String(id))}.png`;
  return `<img class="${className}" src="${source}" alt="${escapeHtml(name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('asset-failed')">`;
}
function skillIcon(icon, name) {
  if(!icon) return "";
  const source=`https://torappu.prts.wiki/assets/build_skill_icon/${encodeURIComponent(String(icon))}.png`;
  return `<img class="skill-icon" src="${source}" alt="" title="${escapeHtml(name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('asset-failed')">`;
}
function eliteIcon(phase, className="elite-icon") {
  const value=Math.max(0,Math.min(2,+phase||0));
  return `<img class="${className}" src="/assets/elite/elite${value}.png" alt="${BaseView.phaseNames[value]}" title="${BaseView.phaseNames[value]}">`;
}
const popoverBodies=new Map();
let popoverSerial=0;
function popoverData(html){const id=String(++popoverSerial);popoverBodies.set(id,html);return `data-popover="${id}"`;}
function operatorInfo(id,name,profile,skills=[]) {
  return `<div class="popover-heading">${operatorAvatar(id,name)}<div><strong>${escapeHtml(name)}</strong><small>${BaseView.phaseNames[+profile?.elite||0]} · 等级 ${+profile?.level||1}</small></div>${eliteIcon(profile?.elite)}</div><div class="popover-skills">${skills.length?skills.map(skill=>`<div class="popover-skill">${skillIcon(skill.icon,skill.name)}<div><b>${escapeHtml(skill.name)}</b><small>${BaseView.phaseNames[+skill.unlock?.phase||0]} · 等级 ${skill.unlock?.level||1} 解锁</small><p>${escapeHtml(skill.description||'暂无技能说明')}</p></div></div>`).join(''):'<p class="side-note">该设施没有已解锁的对应技能</p>'}</div>`;
}
function operatorBadge(id,name,profile,className="operator-avatar",skills=[]) {
  return `<button type="button" class="operator-badge" ${popoverData(operatorInfo(id,name,profile,skills))} aria-label="${escapeHtml(name)}，${BaseView.phaseNames[+profile?.elite||0]}，查看基建技能">${operatorAvatar(id,name,className)}${eliteIcon(profile?.elite,'badge-elite')}<b>${escapeHtml(name)}</b></button>`;
}
function skillToken(skill) {
  const unlock=skill.unlock||{};
  const unlockText=unlock.phase==null?"解锁阶段未知":`精英 ${unlock.phase} · Lv.${unlock.level||1} 解锁`;
  return `<span class="skill-token" tabindex="0">${skillIcon(skill.icon,skill.name)}<em>${escapeHtml(skill.name)}</em><span class="skill-tooltip"><b>${escapeHtml(skill.name)}</b><small>${escapeHtml(unlockText)}</small>${escapeHtml(skill.description||"暂无技能说明")}</span></span>`;
}

async function loadCatalog() {
  const data = await request("/api/operators");
  state.catalog = data.operators;
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
  $("orundumTrades").value=Math.min(prev,layout.trade);
  $("shardRecipe").disabled=!shard;
}
$("baseLayout").addEventListener("change",updateLayoutControls);
$("expFactories").addEventListener("change",updateProductControls);
$("shardFactories").addEventListener("change",updateProductControls);
$("orundumTrades").addEventListener("change",updateProductControls);
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
    valuation: {orundum_pricing:$("orundumPricing").value, orundum:+$("orundumValue").value,
      ...($("rockValue").value === "" ? {} : {rock:+$("rockValue").value}),
      ...($("deviceValue").value === "" ? {} : {device:+$("deviceValue").value})},
    drone_target: $("droneTarget").value,
    gold_net_target_per_day: +$("goldNetTarget").value || 0,
    objective_mode: $("objectiveMode").value,
    schedule_mode: $("scheduleMode").value,
    lock_dorm_helper: $("lockDormHelper").checked,
    enable_fiammetta: !$("enableFiammetta").disabled && $("enableFiammetta").checked,
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
  finally { button.disabled = false; button.innerHTML = "<span>开始计算</span><b>→</b>"; }
});

function renderResults(data) {
  state.lastResult = data;
  hideOperatorPopover();
  popoverBodies.clear();
  const m = data.rotation?.average_metrics || data.metrics;
  $("emptyState").classList.add("hidden");
  $("results").classList.remove("hidden");
  selectResultTab("overview");
  $("solverBadge").textContent = data.solver;
  $("lmdKpi").textContent = number(BaseView.income(m).net);
  $("lmdKpi").classList.toggle('negative',BaseView.income(m).net<0);
  $("lmdKpiNote").textContent = incomeBreakdown(m);
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
  renderAllocationAudit(data.allocation_audit);
  renderBars(m);
  renderRotation(data.rotation);
  renderYieldCurve(data.rotation?.production_curve);
  const audit=data.search_audit;
  const valuation=data.valuation, objective=data.objective;
  const comparison=objective?.comparison;
  const objectiveAudit=comparison ? (comparison.same_semantic_assignment && comparison.same_work_durations!==false ? `目标交叉审计：在${comparison.scope}内，“${objective.label}”和“${comparison.alternate_label}”收敛到相同的实质房间组合与工时（已忽略同类房间编号互换）；这是本 Box 的求解结果，不代表两套公式相同。` : `目标交叉审计：“${objective.label}”与“${comparison.alternate_label}”在完整 A/B 组合或工时上存在差异；备选方案龙门币净收入 ${BaseView.income(comparison.alternate_metrics).net}/日、经验 ${comparison.alternate_metrics.exp_per_day}/日、赤金净流 ${signed(comparison.alternate_metrics.gold_net_per_day)}/日${comparison.alternate_work_durations?`，工时 A ${comparison.alternate_work_durations.A}h / B ${comparison.alternate_work_durations.B}h`:""}。`) : "";
  const searchWarning=audit ? `求解范围：${audit.claim}。${audit.candidate_operator_pool}；每类房间目标保留 ${audit.candidate_retain_target_per_room_type} 个组合；阶段技能分别按 A ${audit.modeled_shift_hours}h / B ${audit.modeled_shift_hours_b || audit.modeled_shift_hours}h 积分${audit.duration_refinements?`（经 ${audit.duration_refinements} 次时长回代）`:""}；${audit.rotation_strategy}。目标：${objective?.label || "按布局产出"}；硬约束：${objective?.hard_constraints || "使用页面布局"}${objective?.mode === "sanity_value" && valuation ? `；${valuation.note}` : ""}。` : "";
  $("warnings").innerHTML = [objectiveAudit,searchWarning,...data.warnings].filter(Boolean).map(x => `<div class="warning">${escapeHtml(x)}</div>`).join("");
  renderMorale(data.morale, data.rotation);
  const teams = data.rotation?.teams || {A:{support_rooms:data.support_rooms||[],rooms:data.rooms}};
  const workHours=data.rotation?.team_work_hours||{};
  const cycleHours=Object.values(workHours).reduce((sum,value)=>sum+(+value||0),0)||24;
  const staggered=data.rotation?.schedule_mode==="staggered";
  const roomDurations=data.rotation?.room_work_hours||{};
  $("rooms").innerHTML = Object.entries(teams).map(([team,plan])=>{
    const share=(+workHours[team]||cycleHours)/cycleHours, tm=plan.metrics||{};
    const teamSummary=staggered?'<p class="staggered-team-note">房间独立换班；每张设施卡按该房间实际在岗比例折算，与 24 小时曲线一致。</p>':`<div class="team-cycle-summary"><div><span>周期占比</span><strong>${(share*100).toFixed(1)}%</strong><small>${workHours[team]||cycleHours}h / ${cycleHours}h</small></div><div><span>对图表龙门币贡献</span><strong>${number(Math.round(BaseView.income(tm).net*share))}</strong><small>本队满日等效 ${number(Math.roundBaseView.income(tm).net)}</small></div><div><span>对图表经验贡献</span><strong>${number(Math.round((+tm.exp_per_day||0)*share))}</strong><small>本队满日等效 ${number(Math.round(+tm.exp_per_day||0))}</small></div><div><span>对图表赤金净流贡献</span><strong>${signed((+tm.gold_net_per_day||0)*share)}</strong><small>本队满日等效 ${signed(+tm.gold_net_per_day||0)}</small></div></div>`;
    return `<section class="team-room-group"><div class="team-room-title"><strong>${team} 队</strong><span>${staggered?"按设施查看工时":workHours[team] ? `每循环工作 ${workHours[team]} 小时` : "单班方案"}</span></div>${teamSummary}<div class="rooms">${[...(plan.support_rooms||[]),...(plan.rooms||[])].map(room => {
    const event=(data.rotation?.rooms||[]).find(row=>row.room===room.room)?.events?.find(item=>item.team===team);
    const roomShare=staggered?(+(roomDurations[room.room]?.[team]||0)/24):share;
    const rates=event ? Object.values(event.morale_rates||{}).map(Number) : [];
    const rateRange=rates.length ? `${Math.min(...rates)}${Math.max(...rates)!==Math.min(...rates)?`–${Math.max(...rates)}`:""}` : "—";
    const output=roomOutput(room), totalEfficiency=room.key==="power" ? 5+(+room.efficiency||0) : (room.multiplier ? (+room.multiplier-1)*100 : null);
    return `
    <article class="room">
      <div class="room-head"><h3>${escapeHtml(room.room)}</h3><span class="eff">${totalEfficiency==null?`技能 +${room.efficiency}%`:`实际 +${totalEfficiency.toFixed(2)}%`}</span></div>
      <div class="names operator-line">${room.names.map((name,index)=>operatorBadge(room.operators[index],name,room.operator_profiles?.[index],"operator-avatar",(room.details||[]).find(d=>d.operator===name||d.operator===room.operators[index])?.skills||[])).join("")}</div>
      ${output?`<div class="room-output"><span>本队在岗时日产等效</span><strong>${escapeHtml(output)}</strong><small>按 ${(roomShare*24).toFixed(0)}h 在岗折算：${escapeHtml(roomOutput(room,roomShare))}</small></div>`:""}
      ${event ? `<div class="endurance"><span>实际在岗 ${event.scheduled_work_hours}h</span><span>本组合安全上限 ${event.safe_work_hours}h</span><span>心情消耗 ${rateRange}/h</span></div>` : ""}
      ${room.group ? `<span class="confidence">${escapeHtml(room.group)} · MAA 组合候选</span>` : `<span class="confidence">${room.confidence === "direct" ? "直接数值模型" : room.confidence === "state_model" ? "跨设施状态模型" : "保守估算"}</span>`}
      <details class="room-details"><summary>效率与计算明细</summary><div class="eff-ledger">${totalEfficiency!=null?`<span>技能/状态 +${room.efficiency}%</span><span>${room.key==="power"?"基础 +5%":`基础 +${room.names.length}%`}</span><span>${room.key==="power"?`充能 +${totalEfficiency.toFixed(2)}%`:`倍率 ×${(+room.multiplier).toFixed(4)}`}</span>`:""}</div>${(room.mechanic_notes || []).length ? `<div class="skills">机制：${room.mechanic_notes.map(escapeHtml).join("；")}</div>` : ""}</details>
    </article>`}).join("")}</div></section>`;
  }).join("");
  runQuickSimulation(data);
  $("results").scrollIntoView({behavior:"smooth", block:"start"});
}

function renderAllocationAudit(audit) {
  if(!audit){$("allocationAudit").innerHTML='<p class="side-note">暂无分配审计。</p>';return;}
  const rows=(audit.multi_facility_operators||[]).map(row=>`<div class="allocation-row"><span>${operatorAvatar(row.operator_id,row.operator)}<b>${escapeHtml(row.operator)}</b></span><small>${row.skills.map(skill=>`<span>${escapeHtml(skill.facility)} ${skillToken(skill)}</span>`).join("")}</small><strong>${Object.entries(row.assignments||{}).map(([team,rooms])=>`${team}：${rooms.map(escapeHtml).join("、")}`).join(" · ")||"本方案未上班"}</strong></div>`).join("");
  const duplicate=(audit.simultaneous_duplicates||[]).length;
  $("allocationAudit").innerHTML=`<p class="side-note">${escapeHtml(audit.constraint)} ${escapeHtml(audit.rotation_scope)}</p><div class="allocation-status ${duplicate?"warn":"ok"}">${duplicate?`发现 ${duplicate} 处同班重复，结果无效。`:"✓ 同班干员互斥校验通过"}</div>${rows||'<p class="side-note">当前 Box 没有已解锁两种生产设施技能的干员。</p>'}`;
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
  const metric=(label,current,alternate,key)=>`<div><span>${label}</span><strong>${number(Math.round(+current||0))}</strong><small>备选 ${number(Math.round(+alternate||0))} · 差 ${signed((+alternate||0)-(+current||0),3)}</small></div>`;
  $("objectiveComparison").innerHTML=`<div class="comparison-head"><h3>目标函数对照</h3><span class="comparison-state ${converged?"same":"different"}">${converged?"结果收敛":"存在取舍"}</span></div>
    <div class="comparison-metrics">${metric("龙门币净收入",BaseView.income(currentMetrics).net,BaseView.income(alt).net,"lmd_net_after_shards_per_day")}${metric("经验",currentMetrics.exp_per_day,alt.exp_per_day,"exp_per_day")}${metric("赤金制造",currentMetrics.gold_made_per_day,alt.gold_made_per_day,"gold_made_per_day")}${metric("赤金净流",currentMetrics.gold_net_per_day,alt.gold_net_per_day,"gold_net_per_day")}</div>
    <details class="inline-audit"><summary>查看两种目标的组合差异</summary><p class="comparison-copy">当前：<b>${escapeHtml(objective.label)}</b>；备选：<b>${escapeHtml(comparison.alternate_label)}</b>。${converged?"本 Box 的最优候选重合，不表示公式相同。":"切换目标会改变最终方案。"}${comparison.cross_candidate_reranked?" 已执行完整 A/B 候选重排。":""}</p><div class="room-differences">${differences.map(row=>`<div><strong>${row.team} 班 · ${escapeHtml(row.room_type)}</strong><p><span>当前</span>${row.current.map(group=>escapeHtml(group.join(" / "))).join("；")}</p><p><span>备选</span>${row.alternate.map(group=>escapeHtml(group.join(" / "))).join("；")}</p></div>`).join("")||'<p class="side-note">实质房间组合与工时相同。</p>'}</div></details>`;
}

function incomeBreakdown(metrics) {
  const {gross,cost}=BaseView.income(metrics);
  return `赤金贸易 ${number(Math.round(gross))} − 搓玉消耗 ${number(Math.round(cost))}`;
}

function signed(value, digits = 2) {
  const rounded = Number(value || 0).toFixed(digits).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
  return `${+value >= 0 ? "+" : ""}${rounded}`;
}

function renderProductionMonitor(m) {
  const rows = [
    {kind:"lmd", icon:"龙", name:"龙门币净收入", total:BaseView.income(m).net, unit:"/ 日", rate:BaseView.income(m).net/24, note:incomeBreakdown(m)},
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
    <p class="side-note">站内净流 ${signed(m.gold_production_net_per_day)} / 日。</p>`;
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
  <details class="inline-audit"><summary>分流口径</summary><p class="side-note">先恢复进库存，达到 ${m.drone_capacity || 235} 架后暂停；仅在收取节点投入。解析曲线与随机模拟使用相同分流。</p></details>`;
}

function renderCrossRoomFlows(flows) {
  if (!flows.length) {
    $("crossRoomPanel").innerHTML = '<p class="side-note">当前组合没有触发已建模的跨房间生产状态。</p>';
    return;
  }
  $("crossRoomPanel").innerHTML = flows.map(flow => `<details class="state-flow ${flow.active === false ? "inactive" : ""}">
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
    $("operatorTimeline").innerHTML='<p class="side-note">当前 Box 不足以生成两套互斥班组。</p>';
    return;
  }
  const handoverTimes=(rotation.handover_events||[]).map(node=>hourLabel(node.time)).join(' / ');
  $("rotationPattern").textContent=`换班 ${handoverTimes||'—'} · 上线间隔 ${rotation.collection_interval_hours}h`;
  const cycle=rotation.cycle_hours;
  const axisStep=Math.max(2,Math.ceil(cycle/12));
  const tickHours=Array.from({length:Math.floor(cycle/axisStep)+1},(_,i)=>i*axisStep);
  if(tickHours.at(-1)!==cycle)tickHours.push(cycle);
  const ticks=tickHours.map(hour=>`<span class="${hour===0?'axis-first':hour===cycle?'axis-last':''}" style="left:${hour/cycle*100}%">${hour}h</span>`).join('');
  const droneEvents=rotation.production_curve?.drone_events||[];
  const collectionHours=[...new Set(droneEvents.map(event=>event.minute/60))];
  const collectionLines=collectionHours.filter(hour=>hour>0&&hour<cycle).map(hour=>`<i class="collection-line" style="left:${hour/cycle*100}%" title="${hourLabel(hour)} 收取"></i>`).join('');
  const rows=(rotation.rooms||[]).map(room=>`<div class="timeline-row room-timeline-row"><strong title="${escapeHtml(room.room)}">${escapeHtml(room.room)}</strong><div class="timeline-lane">${collectionLines}${droneEvents.flatMap(event=>(event.targets||[]).filter(target=>String(target.target||'').split('：')[0]===room.room).map(target=>`<i class="timeline-drone" style="left:${Math.min(99,event.minute/60/cycle*100)}%" title="${escapeHtml(`${hourLabel(event.minute/60)} · 无人机 ${Math.round(target.drones)} 架 → ${target.label}`)}">⚡</i>`)).join('')}${room.events.map(event=>{
    const left=event.start/cycle*100, width=(event.end-event.start)/cycle*100;
    const time=`${hourLabel(event.start)}–${hourLabel(event.end)}`;
    const detail=`<div class="segment-popover-title"><b>${escapeHtml(room.room)} · ${event.team} 班</b><span>${time}${event.continuation?' · 延续前一日夜班':''}</span><small>实际在岗 ${event.scheduled_work_hours}h · 最低结束心情 ${event.morale_min_end??'—'}</small></div>${event.names.map((name,index)=>operatorInfo(event.operators[index],name,event.operator_profiles?.[index],(event.details||[]).find(item=>item.operator===name||item.operator===event.operators[index])?.skills||[])).join('')}`;
    return `<button type="button" class="timeline-event room-event work-${event.team.toLowerCase()} segment-compact" data-count="${event.names.length}" style="left:${left}%;width:${width}%" ${popoverData(detail)} aria-label="${escapeHtml(`${room.room}，${time}，${event.team} 班，${event.names.join('、')}，查看名单与技能`)}"><span class="room-team">${event.team}</span><span class="segment-count">${event.names.length}人</span><span class="operator-chips">${event.names.map((name,index)=>`<span class="timeline-person">${operatorAvatar(event.operators[index],name,'timeline-avatar')}${eliteIcon(event.operator_profiles?.[index]?.elite,'timeline-elite')}<b>${escapeHtml(name)}</b></span>`).join('')}</span></button>`;
  }).join('')}</div></div>`).join('');
  $("operatorTimeline").innerHTML=`<div class="timeline-axis"><strong>设施 / 班组</strong><div>${ticks}</div></div>${rows}<p class="timeline-note">悬浮或点击班段查看完整名单与技能。窄时段显示班组与人数；条形长度仍对应实际工时。</p>`;
  requestAnimationFrame(fitTimelineSegments);
}

function fitTimelineSegments() {
  document.querySelectorAll('.room-event').forEach(element=>{
    const mode=BaseView.segmentMode(element.getBoundingClientRect().width,+element.dataset.count);
    element.classList.remove('segment-compact','segment-portraits','segment-full');
    element.classList.add(`segment-${mode}`);
  });
}

const curveLabels={lmd_per_day:"赤金贸易收入",lmd_net_after_shards_per_day:"龙门币净收入",lmd_shard_cost_per_day:"搓玉消耗",exp_per_day:"作战经验",gold_net_per_day:"赤金净流量",gold_made_per_day:"赤金制造",gold_used_per_day:"赤金消耗",orundum_per_day:"合成玉",drones_per_day:"无人机库存"};

function chartColors() {
  const style=getComputedStyle(document.documentElement);
  return {text:style.getPropertyValue("--text").trim(),muted:style.getPropertyValue("--muted").trim(),line:style.getPropertyValue("--line").trim(),surface:style.getPropertyValue("--surface-2").trim(),accent:style.getPropertyValue("--accent").trim(),blue:style.getPropertyValue("--blue").trim(),cyan:style.getPropertyValue("--cyan").trim(),red:style.getPropertyValue("--red").trim()};
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
  const transitions=(state.lastResult?.rotation?.handover_events||[]).map(event=>hourLabel(event.time)).join(' / ') || '本周期无换班';
  const hours=state.lastResult?.rotation?.team_work_hours||{}, cycle=Object.values(hours).reduce((sum,value)=>sum+(+value||0),0);
  const weighting=Object.entries(hours).map(([team,value])=>`${team} ${value}h`).join(" + ");
  $("yieldCurve").innerHTML=`<div class="curve-summary"><div><span>${key==="drones_per_day"?"24h 末库存":"24h 累计"}</span><strong>${signed(final)} ${escapeHtml(label)}</strong></div><div><span>${key==="drones_per_day"?"恢复速率范围":"小时速率范围"}</span><strong>${signed(Math.min(...rates))} ～ ${signed(Math.max(...rates))}</strong><small>每分钟 ${signed(Math.min(...rates)/60,3)} ～ ${signed(Math.max(...rates)/60,3)}</small></div><div><span>实际换班时刻</span><strong>${escapeHtml(transitions)}</strong></div><div><span>排程口径</span><strong>${escapeHtml(weighting||"房间独立")}</strong><small>${cycle?`平均工时仅作摘要；曲线按房间逐段积分`:`直接使用单班日产`}</small></div></div><div id="yieldChartCanvas" class="echart yield-echart" role="img" aria-label="${escapeHtml(label)}累计与实时速率"></div><p class="side-note">${escapeHtml(curve.note)}</p>`;
  if (!window.echarts) return;
  state.charts.yield?.dispose();
  const colors=chartColors(), cumulativeLabel=key==="drones_per_day"?"当前库存":`累计${label}`;
  const droneData=(curve.drone_events||[]).map(event=>{
    const point=points.find(item=>item.minute===event.minute);
    return {value:[event.minute/60,+point?.cumulative?.[key]||0],event};
  });
  state.charts.yield=echarts.init(document.getElementById("yieldChartCanvas"));
  state.charts.yield.setOption({
    animationDuration:450,color:[colors.accent,colors.blue,colors.cyan],
    textStyle:{color:colors.muted,fontFamily:"-apple-system, BlinkMacSystemFont, PingFang SC, sans-serif"},
    legend:{top:2,textStyle:{color:colors.text,fontSize:11}},
    grid:{left:58,right:58,top:42,bottom:46},
    tooltip:{trigger:"axis",backgroundColor:colors.surface,borderColor:colors.line,textStyle:{color:colors.text},formatter(items){const hour=items[0]?.axisValue??0;const rows=items.map(item=>`${item.marker}${item.seriesName}：<b>${number(Math.round(item.value[1]*1000)/1000)}</b>${item.seriesIndex===1?" /h":""}`);return `<b>${hour}h</b><br>${rows.join("<br>")}`;}},
    xAxis:{type:"value",min:0,max:24,interval:2,axisLabel:{color:colors.muted,formatter:"{value}h"},axisLine:{lineStyle:{color:colors.line}},splitLine:{lineStyle:{color:colors.line,opacity:.55}}},
    yAxis:[{type:"value",name:"累计",nameTextStyle:{color:colors.muted},axisLabel:{color:colors.muted},splitLine:{show:false}},{type:"value",name:"每小时",nameTextStyle:{color:colors.muted},axisLabel:{color:colors.muted},splitLine:{show:false}}],
    dataZoom:[{type:"inside",xAxisIndex:0,filterMode:"none"},{type:"slider",xAxisIndex:0,height:15,bottom:7,brushSelect:false,borderColor:colors.line,fillerColor:colors.line,textStyle:{color:colors.muted}}],
    series:[
      {name:cumulativeLabel,type:"line",showSymbol:false,smooth:.18,yAxisIndex:0,lineStyle:{width:3},areaStyle:{opacity:.08},data:points.map(point=>[point.minute/60,+point.cumulative[key]||0])},
      {name:"实时速率",type:"line",showSymbol:false,step:"end",yAxisIndex:1,lineStyle:{width:2,type:"dashed"},data:points.map(point=>[point.minute/60,+point.rates_per_hour[key]||0])},
      {name:"无人机投入",type:"scatter",yAxisIndex:0,symbolSize:9,data:droneData,tooltip:{formatter(params){const e=params.data.event;return `<b>${e.minute/60}h · ${e.team}</b><br>投入 ${number(Math.round(e.drones_spent))} 架<br>${(e.targets||[]).map(x=>`${escapeHtml(x.label)} ${number(Math.round(x.drones))}`).join("<br>")||"保留"}`;}}}
    ]
  });
}

$("curveMetric").addEventListener("change",()=>renderYieldCurve(state.lastResult?.rotation?.production_curve));

async function simulateSchedule(result, days, trials) {
  return request("/api/simulate", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({rooms:result.rooms, metrics:result.metrics, rotation:result.rotation,
      days, trials, seed:$("simSeed").value || undefined,
      inventory_policy:$("simInventoryPolicy").value})
  });
}

async function runQuickSimulation(result) {
  const sequence = ++state.quickSimSequence;
  $("quickSimulation").innerHTML = '<div class="sim-loading"><i></i><span>正在快进 30 天 × 300 次…</span></div>';
  try {
    const data=await simulateSchedule(result,30,300);
    if (sequence !== state.quickSimSequence) return;
    const d=data.difference_percent, s=data.simulated;
    $("quickSimulation").innerHTML = `<div class="quick-grid">
      <div><span>模拟龙门币净收入</span><strong>${number(Math.round(BaseView.income(s).net))}</strong><small>${signed(d.lmd_net_after_shards_per_day,3)}%</small><small>${incomeBreakdown(s)}</small></div>
      <div><span>模拟赤金净流</span><strong>${signed(s.gold_net_per_day)}</strong><small>根 / 日</small></div>
    </div><p class="convergence ${Math.abs(d.lmd_net_after_shards_per_day || 0) < 1 ? "ok" : "warn"}">${Math.abs(d.lmd_net_after_shards_per_day || 0) < 1 ? "✓ 均值已收敛" : "△ 与解析期望有偏差"}</p><details class="inline-audit"><summary>本轮样本</summary><p class="side-note">首条轨迹：龙门币净收入 ${number(Math.round(BaseView.income(data.sample_run).net))}/日，赤金净流 ${signed(data.sample_run?.gold_net_per_day||0)}/日；种子 ${escapeHtml(data.seed)}。90% 区间 ${number(Math.round(s.lmd_net_p05))}–${number(Math.round(s.lmd_net_p95))}。</p></details>`;
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
  $("moraleAudit").innerHTML = `<div class="comparison-head"><h3>心情与宿舍</h3><span class="comparison-state ${sustainable?"same":"different"}">${sustainable ? "可持续" : "恢复不足"}</span></div><div class="morale-grid">
    <div><span>基础恢复</span><strong>${rotation?.morale?.base_recovery_per_hour || m.base_recovery_per_hour} /h</strong></div>
    <div><span>最慢回满</span><strong>${slowest}h</strong></div>
    <div><span>床位小时</span><strong>${bedLedger}</strong></div>
    <div><span>固定恢复位</span><strong>${locked ? escapeHtml(locked.name) : "未启用"}</strong></div>
  </div><details class="inline-audit"><summary>查看恢复审计</summary><p>${escapeHtml(rotation?.morale?.note || m.note)} ${m.owned_operators} 名干员 / 最低 ${m.minimum_distinct_operators} 名：${m.roster_capacity_ok ? "通过" : "不足"}。</p><p>菲亚梅塔：${fiammetta?.active ? `恢复 ${escapeHtml(fiammetta.target_operator_name)}；两段回满 ${fiammettaAudit.recover_during_b_hours}h / ${fiammettaAudit.recover_during_a_hours}h` : escapeHtml(fiammetta?.note || (m.fiammetta_owned ? "本次未激活" : "当前未拥有"))}。候选恢复干员：${helpers}</p></details>`;
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
    card("龙门币净收入 / 日", number(Math.round(BaseView.income(s).net)), "lmd_net_after_shards_per_day", `<span>${incomeBreakdown(s)}</span><span>90% 区间 ${number(Math.round(s.lmd_net_p05))}–${number(Math.round(s.lmd_net_p95))}</span>`) +
    card("经验 / 日", number(Math.round(s.exp_per_day)), "exp_per_day") +
    card("赤金制造 / 日", s.gold_made_per_day, "gold_made_per_day") +
    card("赤金消耗 / 日", s.gold_used_per_day, "gold_used_per_day") +
    (s.orundum_per_day > 0 ? card("合成玉 / 日", Math.round(s.orundum_per_day), "orundum_per_day") + card("碎片净变化 / 日", signed(s.shards_net_per_day), "shards_made_per_day") : "") +
    `<details class="simulation-notes"><summary>本轮随机轨迹与假设</summary><p>第 1 条轨迹：龙门币净收入 ${number(Math.round(BaseView.income(data.sample_run).net))}/日，赤金净流 ${signed(data.sample_run?.gold_net_per_day||0)}/日；种子 ${escapeHtml(data.seed)}。${data.days} 天 × ${number(data.trials)} 次。${data.assumptions.map(escapeHtml).join(" ")}</p></details>`;
  const entries=(data.collection_events||[]).filter(event=>event.hour<=48);
  $("simulationResult").insertAdjacentHTML("beforeend", `<details class="simulation-notes"><summary>前 48 小时实际收取记录</summary><table><thead><tr><th>时刻</th><th>赤金库存</th><th>碎片库存</th><th>赤金贸易收入</th><th>搓玉消耗</th><th>龙门币净收入</th></tr></thead><tbody>${entries.map(event=>`<tr><td>${event.hour} h</td><td>${signed(event.gold)}</td><td>${signed(event.shards)}</td><td>${number(event.collected.lmd_per_day)}</td><td>${number(event.collected.lmd_shard_cost_per_day)}</td><td>${number(event.collected.lmd_net_after_shards_per_day)}</td></tr>`).join("")}</tbody></table><p>终点未收取：赤金 ${data.pending_output?.gold_made_per_day||0}，源石碎片 ${data.pending_output?.shards_made_per_day||0}。</p><button id="downloadSimulation">下载完整模拟记录</button></details>`);
  document.getElementById("downloadSimulation").addEventListener("click",()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));
    const link=document.createElement("a"); link.href=url; link.download=`simulation-${data.seed}.json`; link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  $("simulationResult").classList.remove("hidden");
}

function renderBars(m) {
  const values = [
    ["龙门币净收入", BaseView.income(m).net, BaseView.income(m).net<0?"red":""], ["作战经验", m.exp_per_day, "blue"],
    ["赤金制造 ×500", m.gold_made_per_day * 500, "gold"], ["赤金消耗 ×500", m.gold_used_per_day * 500, "red"]
  ];
  if(m.orundum_per_day>0) values.push(["合成玉 ×100",m.orundum_per_day*100,"blue"]);
  $("barChart").innerHTML='<div id="resourceBarCanvas" class="echart bar-echart" role="img" aria-label="每日资源产出对比"></div>';
  if (!window.echarts) return;
  state.charts.bars?.dispose();
  const colors=chartColors();
  state.charts.bars=echarts.init(document.getElementById("resourceBarCanvas"));
  state.charts.bars.setOption({
    animationDuration:450,grid:{left:92,right:58,top:8,bottom:26},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"},backgroundColor:colors.surface,borderColor:colors.line,textStyle:{color:colors.text},valueFormatter:value=>number(Math.round(value))},
    xAxis:{type:"value",axisLabel:{color:colors.muted},axisLine:{lineStyle:{color:colors.line}},splitLine:{lineStyle:{color:colors.line,opacity:.5}}},
    yAxis:{type:"category",data:values.map(x=>x[0]),axisLabel:{color:colors.text,fontSize:10},axisLine:{show:false},axisTick:{show:false}},
    series:[{type:"bar",barMaxWidth:18,data:values.map(([,,kind],index)=>({value:values[index][1],itemStyle:{color:{blue:colors.blue,gold:colors.cyan,red:colors.red}[kind]||colors.accent,borderRadius:[0,4,4,0]},label:{show:true,position:"right",color:colors.text,formatter:params=>number(Math.round(params.value))}}))}]
  });
}

window.addEventListener("resize",()=>Object.values(state.charts).forEach(chart=>chart?.resize()));

let popoverTarget=null, popoverPinned=false, popoverTimer=null;
function hideOperatorPopover() {
  clearTimeout(popoverTimer);
  if(popoverTarget)popoverTarget.removeAttribute('aria-describedby');
  popoverTarget=null;popoverPinned=false;$("operatorPopover").hidden=true;
}
function showOperatorPopover(target,pinned=false) {
  const html=popoverBodies.get(target.dataset.popover);if(!html)return;
  clearTimeout(popoverTimer);
  if(popoverTarget&&popoverTarget!==target)popoverTarget.removeAttribute('aria-describedby');
  popoverTarget=target;popoverPinned=pinned;
  const panel=$("operatorPopover");panel.innerHTML=html;panel.hidden=false;
  target.setAttribute('aria-describedby','operatorPopover');
  const rect=target.getBoundingClientRect();
  const width=panel.offsetWidth,height=panel.offsetHeight;
  panel.style.left=`${Math.max(12,Math.min(innerWidth-width-12,rect.left))}px`;
  const below=rect.bottom+10, above=rect.top-height-10;
  panel.style.top=`${Math.max(12,Math.min(innerHeight-height-12,below+height<innerHeight?below:above))}px`;
}
document.addEventListener('pointerover',event=>{
  const target=event.target.closest('[data-popover]');
  if(target&&!target.contains(event.relatedTarget)&&!popoverPinned)showOperatorPopover(target);
  if(event.target.closest('#operatorPopover'))clearTimeout(popoverTimer);
});
document.addEventListener('pointerout',event=>{
  if(popoverPinned)return;
  const container=event.target.closest('[data-popover],#operatorPopover');
  if(container&&!container.contains(event.relatedTarget))popoverTimer=setTimeout(hideOperatorPopover,150);
});
document.addEventListener('focusin',event=>{
  const target=event.target.closest('[data-popover]');if(target)showOperatorPopover(target);
});
document.addEventListener('focusout',event=>{
  if(event.target.closest('[data-popover]')&&!popoverPinned)hideOperatorPopover();
});
document.addEventListener('click',event=>{
  const target=event.target.closest('[data-popover]');
  if(target){if(popoverPinned&&popoverTarget===target)hideOperatorPopover();else showOperatorPopover(target,true);}
  else if(!event.target.closest('#operatorPopover'))hideOperatorPopover();
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideOperatorPopover();});
window.addEventListener('scroll',event=>{if(!$("operatorPopover").contains(event.target))hideOperatorPopover();},true);
window.addEventListener('resize',()=>{fitTimelineSegments();hideOperatorPopover();});
new ResizeObserver(fitTimelineSegments).observe($("operatorTimeline"));
const rosterManager=createRosterManager({getCatalog:()=>state.catalog,getRoster:()=>state.roster,
  avatar:operatorAvatar,eliteIcon,escape:escapeHtml,
  onSave:async operators=>{
    const data=await request('/api/roster',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operators})});
    state.roster=data.operators;renderRoster();message('importMessage',`已保存 ${data.count} 名干员。重新计算后应用新的练度。`);
  }});
$("manageRosterButton").addEventListener('click',()=>rosterManager.open());

loadCatalog().catch(error => { $("catalogStatus").textContent = `载入失败：${error.message}`; });
