/* A draft roster is edited locally; only Save replaces the active roster. */
function createRosterManager({getCatalog, getRoster, onSave, avatar, eliteIcon, skillIcon, escape}) {
  const dialog = document.getElementById('rosterDialog');
  let view="game", profession="", branch="";
  let draft = [], selected = null, byId = new Map(), drag = null, swallowClick = false;
  const node = id => document.getElementById(id);
  const status = text => { node('rosterEditStatus').textContent = text; };
  function move(id, phase) {
    const next = BaseView.moveOperator(draft, getCatalog(), id, phase);
    if (next === draft) return status('该干员不支持这个精英阶段。');
    draft = next; selected = id; render();
    status(phase < 0 ? '已移回候选池，保存后生效。' : '已调整阶段；改变精英阶段时等级重置为 1，可在下方修改。');
  }
  function card(op, owned) {
    const catalog = byId.get(op.id) || op;
    return `<button type="button" class="roster-tile ${selected===op.id?'selected':''}" draggable="false" data-roster-id="${escape(op.id)}" aria-pressed="${selected===op.id}" aria-label="${escape(op.name)}，${catalog.rarity} 星，${owned?BaseView.phaseNames[op.elite]:'未加入'}" style="--rarity:${catalog.rarity}">${avatar(op.id,op.name,'pool-avatar')}<span class="tile-rarity">${'★'.repeat(catalog.rarity)}</span>${owned?eliteIcon(op.elite,'tile-elite')+`<span class="tile-level">Lv.${op.level||1}</span>`:''}<strong>${escape(op.name)}</strong></button>`;
  }
  function renderInspector() {
    const catalog = byId.get(selected), owned = draft.find(op=>op.id===selected);
    if (!catalog) {node('rosterInspector').innerHTML='<p>点击头像选择干员，或直接拖到精英阶段行。支持键盘选择和点击调整。</p>';return;}
    const preview=BaseView.operatorPreview(owned||catalog,byId);
    node('rosterInspector').innerHTML=`<div class="inspector-identity">${avatar(catalog.id,catalog.name,'inspector-avatar')}<div><strong>${escape(catalog.name)}</strong><small>${catalog.rarity} 星 · ${escape(catalog.branch_name||'')} · ${owned?'已加入 Box':'候选干员'}</small></div></div><div class="phase-actions" aria-label="设置精英阶段">${[0,1,2].map(phase=>`<button type="button" data-phase="${phase}" ${phase>BaseView.maxElite(catalog.rarity)?'disabled':''} aria-pressed="${owned?.elite===phase}" title="${BaseView.phaseNames[phase]}">${eliteIcon(phase)}<span>${BaseView.phaseNames[phase]}</span></button>`).join('')}</div>${owned?`<label class="level-editor">等级<input id="rosterLevel" type="number" min="1" max="${BaseView.maxLevel(catalog.rarity,owned.elite)}" value="${owned.level||1}" aria-label="${escape(catalog.name)}的等级"></label><button type="button" class="quiet danger" data-phase="-1">移回候选池</button>`:''}`;
    node('rosterInspector').insertAdjacentHTML('beforeend',`<div class="roster-skill-preview"><div class="skill-icon-strip">${preview.skills.map(skill=>skillIcon(skill.icon,skill.name)).join('')}</div><span>已解锁 ${preview.skills.length} 项基建技能 · 所选设施 8h 单人加成 ${preview.efficiency[node('rosterFacility').value]||0}%</span><details class="skill-description-toggle"><summary>展示技能详情</summary>${preview.skills.map(skill=>`<p><b>${escape(skill.name)}</b> · ${escape(skill.description)}</p>`).join('')}</details></div>`);
  }
  function render() {
    const search = node('rosterFilter').value.trim().toLocaleLowerCase(), rarity = +node('rosterRarity').value;
    const matches = op => (!search || `${op.name} ${op.id}`.toLocaleLowerCase().includes(search)) && (!rarity || byId.get(op.id)?.rarity===rarity) && (!profession||byId.get(op.id)?.profession===profession) && (!branch||byId.get(op.id)?.branch===branch);
    const ownedIds = new Set(draft.map(op=>op.id));
    const sorted = BaseView.sortOperators(draft,byId,node('rosterSort').value,node('rosterFacility').value);
    node('rosterDraftCount').textContent=draft.length;
    node('rosterTiers').innerHTML=view==='game'?`<div class="game-roster-pool">${sorted.filter(matches).map(op=>card(op,true)).join('')||'<p class="pool-empty">没有匹配的已拥有干员</p>'}</div>`:[2,1,0].map(phase=>{
      const all=sorted.filter(op=>op.elite===phase), visible=all.filter(matches);
      return `<section class="roster-tier" data-drop-phase="${phase}"><div class="tier-heading">${eliteIcon(phase)}<strong>${BaseView.phaseNames[phase]}</strong><small>${visible.length} / ${all.length} 人</small></div><div class="tier-pool">${visible.map(op=>card(op,true)).join('')||'<p class="pool-empty">拖入干员，或使用下方阶段按钮</p>'}</div></section>`;
    }).join('');
    const available=BaseView.sortOperators(getCatalog().filter(op=>!ownedIds.has(op.id)&&matches(op)),byId,node('rosterSort').value,node('rosterFacility').value);
    node('rosterAvailableCount').textContent=available.length;
    node('rosterAvailable').innerHTML=available.map(op=>card(op,false)).join('')||'<p class="pool-empty">没有匹配的候选干员</p>';
    renderInspector();
  }
  ['rosterFilter','rosterRarity','rosterSort','rosterFacility'].forEach(id=>node(id).addEventListener(id==='rosterFilter'?'input':'change',render));
  function renderProfessions() {
    const names={PIONEER:'先锋',WARRIOR:'近卫',TANK:'重装',SNIPER:'狙击',CASTER:'术师',MEDIC:'医疗',SUPPORT:'辅助',SPECIAL:'特种'};
    node('rosterProfessions').innerHTML=`<button type="button" data-profession="" aria-pressed="${!profession}">全部职业</button>`+Object.entries(names).map(([key,name])=>`<button type="button" data-profession="${key}" aria-pressed="${profession===key}">${name}</button>${profession===key?`<button type="button" class="branch-choice" data-branch="" aria-pressed="${!branch}">全部分支</button>`+[...new Map(getCatalog().filter(op=>op.profession===key).map(op=>[op.branch,op.branch_name])).entries()].map(([id,name])=>`<button type="button" class="branch-choice" data-branch="${escape(id)}" aria-pressed="${branch===id}">${escape(name||id)}</button>`).join(''):''}`).join('');
  }
  dialog.addEventListener('click',event=>{
    if(swallowClick){swallowClick=false;event.preventDefault();event.stopPropagation();return;}
    const viewButton=event.target.closest('[data-roster-view]');
    if(viewButton){view=viewButton.dataset.rosterView;dialog.querySelectorAll('[data-roster-view]').forEach(button=>button.setAttribute('aria-pressed',String(button===viewButton)));render();}
    const profButton=event.target.closest('[data-profession]'),branchButton=event.target.closest('[data-branch]');
    if(profButton){profession=profButton.dataset.profession;branch='';renderProfessions();render();}
    if(branchButton){branch=branchButton.dataset.branch;renderProfessions();render();}
    const tile=event.target.closest('[data-roster-id]');
    if(tile){selected=tile.dataset.rosterId;render();node('rosterInspector').querySelector('button:not(:disabled)')?.focus({preventScroll:true});}
    const phase=event.target.closest('[data-phase]');
    if(phase&&selected)move(selected,+phase.dataset.phase);
  });
  dialog.addEventListener('change',event=>{
    if(event.target.id!=='rosterLevel')return;
    const op=draft.find(op=>op.id===selected);
    const level=Number(event.target.value);
    if(op)op.level=Math.max(1,Math.min(BaseView.maxLevel(byId.get(selected).rarity,op.elite),Math.trunc(level)||1));
    renderInspector();status('等级已更新，保存后生效。');
  });
  // Pointer capture keeps dragging consistent across Safari, mouse and touch.
  // The inspector buttons provide the equivalent keyboard operation.
  function finishDrag() {
    drag?.ghost?.remove();drag=null;
    dialog.querySelectorAll('.drag-over,.dragging').forEach(n=>n.classList.remove('drag-over','dragging'));
  }
  dialog.addEventListener('pointerdown',event=>{
    swallowClick=false;
    const tile=event.target.closest('[data-roster-id]');
    if(!tile||event.button!==0)return;
    swallowClick=false;
    drag={id:tile.dataset.rosterId,tile,x:event.clientX,y:event.clientY,pointer:event.pointerId};
    tile.setPointerCapture(event.pointerId);
  });
  dialog.addEventListener('pointermove',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;
    if(!drag.ghost&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<6)return;
    event.preventDefault();
    if(!drag.ghost){
      drag.ghost=drag.tile.cloneNode(true);drag.ghost.className='roster-tile drag-ghost';
      drag.ghost.removeAttribute('data-roster-id');drag.ghost.style.width=`${drag.tile.offsetWidth}px`;
      dialog.append(drag.ghost);drag.tile.classList.add('dragging');
    }
    drag.ghost.style.left=`${event.clientX+8}px`;drag.ghost.style.top=`${event.clientY+8}px`;
    dialog.querySelectorAll('.drag-over').forEach(n=>n.classList.remove('drag-over'));
    document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-drop-phase]')?.classList.add('drag-over');
    const scroll=node('rosterTiers').parentElement,rect=scroll.getBoundingClientRect();
    if(event.clientY<rect.top+28)scroll.scrollTop-=18;
    else if(event.clientY>rect.bottom-28)scroll.scrollTop+=18;
  });
  dialog.addEventListener('pointerup',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;
    const id=drag.id, tile=drag.tile, moved=!!drag.ghost;
    const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-drop-phase]');
    finishDrag();
    if(tile.hasPointerCapture(event.pointerId))tile.releasePointerCapture(event.pointerId);
    if(moved){swallowClick=true;setTimeout(()=>{swallowClick=false;},0);if(target)move(id,+target.dataset.dropPhase);}
  });
  dialog.addEventListener('pointercancel',finishDrag);
  dialog.addEventListener('close',finishDrag);
  node('closeRosterButton').addEventListener('click',()=>dialog.close());
  node('saveButton').addEventListener('click',async()=>{
    const button=node('saveButton');button.disabled=true;
    try{await onSave(draft);dialog.close();}catch(error){status(`保存失败：${error.message}`);}finally{button.disabled=false;}
  });
  node('clearButton').addEventListener('click',()=>{draft=[];render();status('已清空草稿。可关闭窗口取消，或保存后生效。');});
  return {open(){draft=getRoster().map(op=>({...op}));byId=new Map(getCatalog().map(op=>[op.id,op]));selected=null;renderProfessions();status('拖动头像调整精英阶段；保存后应用到排班。');render();dialog.showModal();node('rosterFilter').focus();}};
}
