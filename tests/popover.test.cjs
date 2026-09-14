const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function harness(){
  const events={}, timers=new Map();let clock=0,id=0;
  const descriptions=Array.from({length:5},()=>({hidden:true}));
  const panel={hidden:true,offsetWidth:380,offsetHeight:200,style:{},contains:node=>node===panel||node===toggle,addEventListener(){},closest:selector=>selector.includes('#operatorPopover')?panel:null,querySelectorAll:()=>descriptions};
  const toggle={dataset:{},textContent:'展示全组技能（5 人）',attrs:{'aria-expanded':'false'},
    getAttribute(key){return this.attrs[key];},setAttribute(key,value){this.attrs[key]=value;},
    closest(selector){return selector.includes('[data-toggle-team-skills]')?this:selector.includes('#operatorPopover')?panel:null;}};
  const context={popoverBodies:new Map([['a','A'],['b','B']]),$:()=>panel,innerWidth:1200,innerHeight:800,
    document:{addEventListener:(name,handler)=>{(events[name]||=[]).push(handler);}},window:{addEventListener(){}},
    setTimeout:(fn,delay)=>{timers.set(++id,{time:clock+delay,fn});return id;},clearTimeout:key=>timers.delete(key)};
  const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
  vm.runInNewContext(source.slice(source.indexOf('let popoverTarget='),source.indexOf("window.addEventListener('scroll'")),context);
  const target=key=>({dataset:{popover:key},isConnected:true,attrs:{},contains(other){return this===other;},
    closest(selector){return selector.includes('[data-popover]')?this:null;},matches(){return true;},
    setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},getBoundingClientRect(){return {left:100,top:100,bottom:140};}});
  const blank={closest(){return null;}};
  return {panel,target,blank,toggle,descriptions,dispatch(name,node,relatedTarget=null,extra={}){for(const handler of events[name]||[])handler({target:node,relatedTarget,...extra});},
    tick(delta){clock+=delta;for(const [key,timer] of [...timers])if(timer.time<=clock){timers.delete(key);timer.fn();}}};
}
test('hover is delayed, cancels on passing by, and closes after leaving even after a click',()=>{
  const h=harness(),a=h.target('a'),b=h.target('b');
  h.dispatch('pointerover',a);h.tick(549);assert.equal(h.panel.hidden,true);
  h.dispatch('pointerout',a,h.blank);h.tick(1000);assert.equal(h.panel.hidden,true);
  h.dispatch('pointerover',a);h.tick(550);assert.equal(h.panel.innerHTML,'A');assert.equal(h.panel.hidden,false);
  h.dispatch('pointerout',a,b);h.dispatch('pointerover',b,a);h.tick(550);assert.equal(h.panel.innerHTML,'B');assert.equal(h.panel.hidden,false);
  h.dispatch('click',b);h.dispatch('pointerout',b,h.blank);h.tick(219);assert.equal(h.panel.hidden,false);
  h.tick(1);assert.equal(h.panel.hidden,true);
  h.dispatch('click',a);assert.equal(h.panel.hidden,false);
  h.dispatch('click',h.blank);assert.equal(h.panel.hidden,true);
});

test('moving into the panel permits interaction without pinning it',()=>{
  const h=harness(),a=h.target('a');
  h.dispatch('pointerover',a);h.tick(550);
  h.dispatch('pointerout',a,h.panel);h.tick(100);h.dispatch('pointerover',h.panel,a);h.tick(300);
  assert.equal(h.panel.hidden,false);
  h.dispatch('click',h.toggle);
  assert.equal(h.toggle.attrs['aria-expanded'],'true');
  assert.ok(h.descriptions.every(node=>!node.hidden));
  h.dispatch('click',h.toggle);
  assert.equal(h.toggle.textContent,'展示全组技能（5 人）');
  assert.ok(h.descriptions.every(node=>node.hidden));
  h.dispatch('pointerout',h.panel,h.blank);h.tick(220);assert.equal(h.panel.hidden,true);
});

test('keyboard can reach details, then dismiss on focus leaving or Escape',()=>{
  const h=harness(),a=h.target('a');
  h.dispatch('focusin',a);assert.equal(h.panel.hidden,false);
  h.dispatch('focusout',a,h.toggle);assert.equal(h.panel.hidden,false);
  h.dispatch('focusout',h.toggle,h.blank);assert.equal(h.panel.hidden,true);
  h.dispatch('click',a);h.dispatch('keydown',a,null,{key:'Escape'});assert.equal(h.panel.hidden,true);
});

test('three- and five-person timeline teams each have one shared skill button',()=>{
  const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
  const context={escapeHtml:String,operatorAvatar:()=>'<img>',eliteIcon:()=>'<img>',skillIcon:()=>'<img>',BaseView:{phaseNames:['初始','精一','精二']}};
  vm.runInNewContext(source.slice(source.indexOf('function operatorInfo('),source.indexOf('function operatorBadge(')),context);
  for(const count of [3,5]){
    const names=Array.from({length:count},(_,i)=>`干员${i}`);
    const markup=context.teamOperatorInfo({names,operators:names,details:names.map(operator=>({operator,skills:[{name:'技能',description:`${operator}的描述`}]}))});
    assert.equal((markup.match(/data-toggle-team-skills/g)||[]).length,1);
    assert.equal((markup.match(/team-skill-descriptions" hidden/g)||[]).length,count);
    assert.equal((markup.match(/<details/g)||[]).length,0);
    assert.ok(names.every(name=>markup.includes(`${name}的描述`)));
  }
});
