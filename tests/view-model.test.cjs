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
test('short shifts retain stacked portraits when full portraits cannot fit',()=>{
  assert.equal(view.segmentMode(90,3),'stacked');
  assert.equal(view.segmentMode(120,5),'stacked');
  assert.equal(view.segmentMode(79,3),'compact');
});
test('timeline pages reach the final day without an empty page or horizontal overflow',()=>{
  assert.deepEqual(view.timelineWindow(72,24,24),{start:24,end:48,hours:24});
  assert.deepEqual(view.timelineWindow(72,24,72),{start:48,end:72,hours:24});
  assert.deepEqual(view.timelineWindow(72,48,48),{start:24,end:72,hours:48});
  assert.deepEqual(view.timelineWindow(72,72,48),{start:0,end:72,hours:72});
  assert.deepEqual(view.timelineWindow(24,72,-24),{start:0,end:24,hours:24});
});
test('cross-midnight shifts are clipped to the visible period without losing the original duration',()=>{
  const event={start:0,end:32},secondDay=view.timelineWindow(72,24,24);
  const clipped=view.clipTimelineEvent(event,secondDay);
  assert.equal(clipped.left,0);assert.ok(Math.abs(clipped.width-100/3)<1e-12);
  assert.deepEqual(event,{start:0,end:32});
  assert.equal(view.clipTimelineEvent({start:0,end:24},secondDay),null);
  assert.equal(view.clipTimelineEvent({start:48,end:72},secondDay),null);
  const later=view.clipTimelineEvent({start:32,end:40},secondDay);
  assert.ok(Math.abs(later.left-100/3)<1e-12);
  assert.ok(later.left+later.width<=100);
});
test('Fiammetta option follows the actual operator id after adding and removing',()=>{
  const original=[{id:'char_123_fang',name:'芬'}];
  assert.equal(view.fiammettaOwned(original),false);
  assert.equal(view.fiammettaOwned([...original,{id:'char_300_phenxi',elite:0}]),true);
  assert.equal(view.fiammettaOwned([{id:'unrelated',name:'菲亚梅塔'}]),false);
});
test('trade explanations separate order speed from Proviso income and use actual room durations',()=>{
  const room={room:'贸易站 1',key:'trade',trade:{expected_lmd:2250,expected_minutes:203.4,notes:['违约订单 +2 赤金']},mechanic_notes:['控制中枢 +7%']};
  const rotation={schedule_mode:'staggered',objective_mode:'layout_output',collection_interval_hours:8,
    room_work_hours:{'贸易站 1':{A:32,B:8}},room_duration_audit:{'贸易站 1':{scores:{A:2.73,B:1.98}}}};
  const info=view.roomDecisionInfo(room,rotation,{});
  assert.equal(info.speedLabel,'订单速度');
  assert.match(info.orderSummary,/2,250.*203.4/);
  assert.deepEqual(info.mechanicNotes,['控制中枢 +7%','违约订单 +2 赤金']);
  assert.match(info.rotationSummary,/龙门币/);
  assert.match(info.rotationSummary,/32h.*8h/);
  assert.match(info.rotationSummary,/8h 上线/);
  assert.equal(view.roomDecisionInfo({...room,key:'orundum',trade:null},rotation,{}).orderSummary,'');
  assert.equal(view.roomDecisionInfo(room,{...rotation,schedule_mode:'fixed'},{}).rotationSummary,'');
});
test('recycler explanation uses the saved result ownership audit',()=>{
  const room={key:'recycle'};
  const missing={operator:'旅骨',owned:false,assignments:{}};
  assert.match(view.roomDecisionInfo(room,{}, {recycle_specialists:[missing]}).specialistSummary,/旅骨.*未在本次计算/);
  assert.equal(view.roomDecisionInfo(room,{}, {recycle_specialists:[{...missing,owned:true,assignments:{A:['回收站']}}]}).specialistSummary,'');
});
test('training, unlocked skills and facility efficiency use the selected promotion and level',()=>{
  const definitions=[{id:'a',name:'甲',rarity:6,previews:[{elite:0,level:1,skills:[1],efficiency:{gold:5,power:20}},{elite:1,level:1,skills:[1,2],efficiency:{gold:35,power:20}}]},
    {id:'b',name:'乙',rarity:4,previews:[{elite:0,level:1,skills:[1],efficiency:{gold:20,power:5}}]}];
  const byId=new Map(definitions.map(op=>[op.id,op]));
  const owned=[{id:'a',name:'甲',elite:0,level:50},{id:'b',name:'乙',elite:1,level:60}];
  assert.deepEqual(view.sortOperators(owned,byId,'elite').map(op=>op.id),['b','a']);
  assert.deepEqual(view.sortOperators(owned,byId,'efficiency','gold').map(op=>op.id),['b','a']);
  assert.deepEqual(view.sortOperators(owned,byId,'efficiency','power').map(op=>op.id),['a','b']);
  assert.equal(view.operatorPreview(owned[0],byId).skills.length,1);
  assert.equal(view.operatorPreview({...owned[0],elite:1,level:1},byId).skills.length,2);
});
test('facility comparison pairs matching rooms even when the second team is reordered',()=>{
  const a={room:'贸易站1',names:['但书']},b={room:'贸易站1',names:['拉普兰德']},power={room:'发电站1',names:['红云']};
  const result={rotation:{teams:{A:{rooms:[a],support_rooms:[power]},B:{rooms:[{room:'制造站1',names:['温蒂']},b]}}}};
  const before=JSON.stringify(result),facilities=view.facilityAssignments(result);
  assert.deepEqual(facilities.map(x=>x.name),['贸易站1','发电站1','制造站1']);
  assert.deepEqual(facilities[0].teams.map(x=>[x.team,x.room.names[0]]),[['A','但书'],['B','拉普兰德']]);
  assert.equal(facilities[1].teams[0].room,power);
  assert.equal(JSON.stringify(result),before);
});
test('facility comparison includes a single-team plan and every support facility',()=>{
  const result={rooms:[{room:'制造站1'}],support_rooms:[{room:'回收站'},{room:'控制中枢'}]};
  assert.deepEqual(view.facilityAssignments(result).map(x=>[x.name,x.teams.map(t=>t.team)]),[['制造站1',['A']],['回收站',['A']],['控制中枢',['A']]]);
  assert.deepEqual(view.facilityAssignments({}),[]);
});
