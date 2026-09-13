const test = require('node:test');
const assert = require('node:assert/strict');
const view = require('../web/view-model.js');
const catalog = [
  {id:'six',name:'菲亚梅塔',rarity:6}, {id:'three',name:'芬',rarity:3},
  {id:'two',name:'黑角',rarity:2}, {id:'four',name:'阿消',rarity:4}
];
test('dragging adds and moves once, preserves the source and resets the level only on phase change',()=>{
  const original=[{id:'six',name:'菲亚梅塔',elite:1,level:70,potential:4}];
  const next=view.moveOperator(original,catalog,'six',2);
  assert.equal(next.length,1);assert.equal(next[0].level,1);assert.equal(next[0].potential,4);
  assert.equal(original[0].elite,1);
  assert.equal(view.moveOperator(original,catalog,'six',1)[0].level,70);
  assert.equal(view.moveOperator(next,catalog,'six',-1).length,0);
});
test('unsupported promotions and foreign dragged values cannot alter roster',()=>{
  const empty=[];
  assert.equal(view.moveOperator(empty,catalog,'three',2),empty);
  assert.equal(view.moveOperator(empty,catalog,'two',1),empty);
  assert.equal(view.moveOperator(empty,catalog,'foreign',2),empty);
  assert.equal(view.moveOperator(empty,catalog,'six',NaN),empty);
  assert.equal(view.moveOperator(empty,catalog,'three',1)[0].elite,1);
});
test('owned cards sort by rarity then Chinese name, without mutating the source',()=>{
  const source=[catalog[1],catalog[0],catalog[3],catalog[2]];
  assert.deepEqual(view.sortOperators(source,new Map(catalog.map(x=>[x.id,x]))).map(x=>x.id),['six','four','three','two']);
  assert.equal(source[0].id,'three');
  assert.equal(view.sortOperators(source,new Map(),'name')[0].name,'阿消');
});
test('cash display subtracts shard expenses once and permits negative daily income',()=>{
  assert.deepEqual(view.income({lmd_per_day:10000,lmd_shard_cost_per_day:16000}),{gross:10000,cost:16000,net:-6000});
  assert.equal(view.income({lmd_per_day:10000,lmd_shard_cost_per_day:16000,lmd_net_after_shards_per_day:-6000}).net,-6000);
  assert.equal(view.income({lmd_per_day:10000}).net,10000);
});
test('22–24 hour bands never try to fit five portraits into a two-hour slot',()=>{
  assert.equal(view.segmentMode(64,5),'compact');
  assert.equal(view.segmentMode(270,5),'portraits');
  assert.equal(view.segmentMode(600,5),'full');
});
test('Fiammetta option follows the actual operator id after adding and removing',()=>{
  const original=[{id:'char_123_fang',name:'芬'}];
  assert.equal(view.fiammettaOwned(original),false);
  assert.equal(view.fiammettaOwned([...original,{id:'char_300_phenxi',elite:0}]),true);
  assert.equal(view.fiammettaOwned([{id:'unrelated',name:'菲亚梅塔'}]),false);
});
