const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
function harness(){
  const values={baseLayout:'243',expFactories:'1',shardFactories:'0',orundumTrades:'0',
    collectionInterval:'8',shiftHours:'36',scheduleMode:'staggered',recycleLevel:'3',
    droneTarget:'auto_balance',goldNetTarget:'-20',shardRecipe:'rock',objectiveMode:'layout_output',
    orundumPricing:'custom',orundumValue:'0.75',rockValue:'',deviceValue:''};
  const nodes={};
  function node(id,props={}){
    const result={id,value:'',type:'text',hidden:false,disabled:false,attrs:{},events:{},
      setAttribute(key,value){this.attrs[key]=value;},
      addEventListener(type,handler){(this.events[type]||=[]).push(handler);},...props};
    nodes[id]=result;return result;
  }
  const controls=Object.entries(values).map(([id,value])=>node(id,{value}));
  for(const [id,checked] of [['recycleBoost',false],['lockDormHelper',true],['enableFiammetta',true]]){
    controls.push(node(id,{type:'checkbox',checked}));
  }
  node('planSettings',{querySelectorAll:()=>controls});
  node('settingsToggle');node('settingsChanged',{hidden:true});node('optimizeButton');
  const state={lastResult:null,resultSettingsSnapshot:null,
    roster:Array.from({length:21},(_,i)=>({id:`operator_${i}`,elite:2,level:80}))};
  const context={state,$:id=>nodes[id]};
  vm.runInNewContext(source.slice(source.indexOf('function setSettingsOpen('),source.indexOf('function selectResultTab(')),context);
  return {state,nodes,context,dispatch(type){for(const handler of nodes.planSettings.events[type]||[])handler();}};
}

test('settings collapse preserves values and reports no stale result before calculation',()=>{
  const h=harness(),before=h.context.captureSettingsSnapshot();
  h.context.setSettingsOpen(false);
  assert.equal(h.nodes.planSettings.hidden,true);
  assert.equal(h.nodes.settingsToggle.attrs['aria-expanded'],'false');
  h.context.setSettingsOpen(true);
  assert.equal(h.nodes.settingsToggle.attrs['aria-expanded'],'true');
  assert.equal(h.context.captureSettingsSnapshot(),before);
  h.nodes.collectionInterval.value='12';h.dispatch('change');
  assert.equal(h.nodes.settingsChanged.hidden,true);
});

test('editing a completed plan marks the result stale and reverting clears the notice',()=>{
  const h=harness();
  h.context.acceptResultSettings({metrics:{}},h.context.captureSettingsSnapshot());
  assert.equal(h.nodes.planSettings.hidden,true);
  assert.equal(h.nodes.settingsChanged.hidden,true);
  h.context.setSettingsOpen(true);
  h.nodes.goldNetTarget.value='-15';h.dispatch('input');
  assert.equal(h.nodes.settingsChanged.hidden,false);
  h.nodes.goldNetTarget.value='-20';h.dispatch('input');
  assert.equal(h.nodes.settingsChanged.hidden,true);
  h.nodes.lockDormHelper.checked=false;h.dispatch('change');
  assert.equal(h.nodes.settingsChanged.hidden,false);
  h.nodes.lockDormHelper.checked=true;h.dispatch('change');
  assert.equal(h.nodes.settingsChanged.hidden,true);
});

test('roster promotion and level changes invalidate results, but roster ordering does not',()=>{
  const h=harness();
  h.context.acceptResultSettings({metrics:{}},h.context.captureSettingsSnapshot());
  h.state.roster.reverse();h.context.updateSettingsChanged();
  assert.equal(h.nodes.settingsChanged.hidden,true);
  h.state.roster[0].level=79;h.context.updateSettingsChanged();
  assert.equal(h.nodes.settingsChanged.hidden,false);
  h.state.roster[0].level=80;h.context.updateSettingsChanged();
  assert.equal(h.nodes.settingsChanged.hidden,true);
  h.state.roster[0].elite=1;h.context.updateSettingsChanged();
  assert.equal(h.nodes.settingsChanged.hidden,false);
  h.state.roster[0].elite=2;
  const removed=h.state.roster.pop();h.context.updateSettingsChanged();
  assert.equal(h.nodes.settingsChanged.hidden,false);
  h.state.roster.push(removed);h.context.updateSettingsChanged();
  assert.equal(h.nodes.settingsChanged.hidden,true);
});

test('a pending calculation retains its submitted settings when the user edits the draft',async()=>{
  const h=harness();let finish,submitted;
  Object.assign(h.context,{
    hideMessage(){},message(){},renderCalculationProgress(){},
    calculationJob(kind,payload){submitted={kind,payload};return new Promise(resolve=>{finish=resolve;});},
    renderResults(data,snapshot){h.context.acceptResultSettings(data,snapshot);},
  });
  vm.runInNewContext(source.slice(source.indexOf('$("optimizeButton").addEventListener("click"'),source.indexOf('function renderResults(')),h.context);
  const pending=h.nodes.optimizeButton.events.click[0]();
  assert.equal(submitted.kind,'optimize');
  assert.equal(submitted.payload.collection_interval_hours,8);
  h.nodes.collectionInterval.value='12';h.dispatch('change');
  h.context.setSettingsOpen(false);
  finish({metrics:{}});await pending;
  assert.equal(h.nodes.planSettings.hidden,false);
  assert.equal(h.nodes.settingsChanged.hidden,false);
  assert.equal(h.nodes.optimizeButton.disabled,false);
  h.nodes.collectionInterval.value='8';h.dispatch('change');
  assert.equal(h.nodes.settingsChanged.hidden,true);
});

test('returning to the submitted values while calculation runs allows settings to collapse',()=>{
  const h=harness(),snapshot=h.context.captureSettingsSnapshot();
  h.nodes.collectionInterval.value='12';
  h.nodes.collectionInterval.value='8';
  h.context.acceptResultSettings({metrics:{}},snapshot);
  assert.equal(h.nodes.planSettings.hidden,true);
  assert.equal(h.nodes.settingsChanged.hidden,true);
});
