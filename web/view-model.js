/* Pure presentation rules shared by the browser and regression checks. */
(function (root) {
  const names = new Intl.Collator('zh-CN', {numeric: true});
  const phaseNames = ['未精英化', '精英一', '精英二'];
  function maxElite(rarity) { return rarity <= 2 ? 0 : rarity === 3 ? 1 : 2; }
  function maxLevel(rarity, elite) {
    return ({1:[30],2:[30],3:[40,55],4:[45,60,70],5:[50,70,80],6:[50,80,90]}[rarity] || [50,80,90])[elite] || 1;
  }
  function moveOperator(roster, catalog, id, phase) {
    const item = catalog.find(op => op.id === id);
    if (!item || ![-1,0,1,2].includes(phase) || phase > maxElite(item.rarity)) return roster;
    if (phase === -1) return roster.filter(op => op.id !== id);
    const previous = roster.find(op => op.id === id);
    const op = {...(previous || {id, name:item.name, potential:1}), elite:phase,
      level: previous?.elite === phase ? Math.min(previous.level || 1, maxLevel(item.rarity, phase)) : 1};
    return previous ? roster.map(value => value.id === id ? op : value) : [...roster, op];
  }
  function operatorPreview(op, byId) {
    const catalog=byId.get(op.id)||op;
    return [...(catalog.previews||[])].reverse().find(stage=>stage.elite<(op.elite||0)||(stage.elite===(op.elite||0)&&stage.level<=(op.level||1)))||{skills:[],efficiency:{}};
  }
  function sortOperators(operators, byId, mode='rarity', facility='gold') {
    const score=op=>mode==='elite'?(op.elite||0)*100+(op.level||1):mode==='skills'?operatorPreview(op,byId).skills.length:mode==='efficiency'?(operatorPreview(op,byId).efficiency[facility]||0):0;
    return [...operators].sort((a,b)=>{
      const rarity=(byId.get(b.id)?.rarity||b.rarity||0)-(byId.get(a.id)?.rarity||a.rarity||0);
      return (mode==='name'?0:score(b)-score(a)||rarity)||names.compare(a.name,b.name);
    });
  }
  function income(metrics = {}) {
    const gross = Number(metrics.lmd_per_day) || 0, cost = Number(metrics.lmd_shard_cost_per_day) || 0;
    return {gross, cost, net:metrics.lmd_net_after_shards_per_day == null ? gross-cost : Number(metrics.lmd_net_after_shards_per_day)};
  }
  function fiammettaOwned(roster) { return roster.some(op => op.id === "char_300_phenxi"); }
  function segmentMode(width, count) {
    if (width < 44 + count * 38) return 'compact';
    return width < 44 + count * 96 ? 'portraits' : 'full';
  }
  function roomDecisionInfo(room, rotation={}, allocation={}) {
    const economy=room.key==='trade'?room.trade:room.key==='orundum'?room.orundum:null;
    const mechanicNotes=[...new Set([...(room.mechanic_notes||[]),...(economy?.notes||[])])];
    const speedLabel=['trade','orundum'].includes(room.key)?'订单速度':room.key==='recycle'?'转化速度':'实际';
    const orderSummary=room.key==='trade'&&economy
      ? `平均每单 ${Number(economy.expected_lmd).toLocaleString('zh-CN')} 龙门币 · 基础用时 ${Number(economy.expected_minutes).toLocaleString('zh-CN')} 分钟`
      : '';
    const durations=rotation.room_work_hours?.[room.room], audit=rotation.room_duration_audit?.[room.room];
    let rotationSummary='';
    if (rotation.schedule_mode==='staggered'&&durations&&audit?.scores&&['trade','orundum','recycle'].includes(room.key)) {
      const basis=rotation.objective_mode==='sanity_value'&&room.key!=='recycle'?'等效理智收益':room.key==='trade'?'龙门币收益':room.key==='orundum'?'合成玉产量':'转化次数';
      rotationSummary=`按${basis}、心情和休息时间选择 A ${durations.A}h / B ${durations.B}h；换班仅在每 ${rotation.collection_interval_hours}h 上线的节点进行。`;
    }
    const missing=room.key==='recycle'?(allocation.recycle_specialists||[]).filter(op=>!op.owned).map(op=>op.operator):[];
    const specialistSummary=missing.length?`${missing.join('、')}未在本次计算的 Box 中，可在干员管理中补充。`:'';
    return {speedLabel,orderSummary,mechanicNotes,rotationSummary,specialistSummary};
  }
  function facilityAssignments(result) {
    const teams=result.rotation?.teams||{A:{rooms:result.rooms||[],support_rooms:result.support_rooms||[]}};
    const facilities=new Map();
    for(const [team,plan] of Object.entries(teams)) {
      for(const room of [...(plan.rooms||[]),...(plan.support_rooms||[])]) {
        if(!facilities.has(room.room))facilities.set(room.room,{name:room.room,teams:[]});
        facilities.get(room.room).teams.push({team,room});
      }
    }
    return [...facilities.values()];
  }
  const api = {facilityAssignments, operatorPreview, phaseNames, maxElite, maxLevel, moveOperator, sortOperators, income, segmentMode, fiammettaOwned, roomDecisionInfo};
  root.BaseView = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);
