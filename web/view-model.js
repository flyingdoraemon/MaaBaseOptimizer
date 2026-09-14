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
  const api = {operatorPreview, phaseNames, maxElite, maxLevel, moveOperator, sortOperators, income, segmentMode, fiammettaOwned};
  root.BaseView = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);
