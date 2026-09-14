const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function harness(){
  const events={}, timers=new Map();let clock=0,id=0;
  const panel={hidden:true,offsetWidth:380,offsetHeight:200,style:{},contains:node=>node===panel,addEventListener(){},closest:selector=>selector.includes('#operatorPopover')?panel:null};
  const context={popoverBodies:new Map([['a','A'],['b','B']]),$:()=>panel,innerWidth:1200,innerHeight:800,
    document:{addEventListener:(name,handler)=>{(events[name]||=[]).push(handler);}},window:{addEventListener(){}},
    setTimeout:(fn,delay)=>{timers.set(++id,{time:clock+delay,fn});return id;},clearTimeout:key=>timers.delete(key)};
  const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
  vm.runInNewContext(source.slice(source.indexOf('let popoverTarget='),source.indexOf("window.addEventListener('scroll'")),context);
  const target=key=>({dataset:{popover:key},isConnected:true,attrs:{},contains(other){return this===other;},
    closest(selector){return selector.includes('[data-popover]')?this:null;},matches(){return true;},
    setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},getBoundingClientRect(){return {left:100,top:100,bottom:140};}});
  const blank={closest(){return null;}};
  return {panel,target,blank,dispatch(name,node,relatedTarget=null){for(const handler of events[name]||[])handler({target:node,relatedTarget});},
    tick(delta){clock+=delta;for(const [key,timer] of [...timers])if(timer.time<=clock){timers.delete(key);timer.fn();}}};
}
test('hover is delayed, transient movement cancels it, and clicking pins until outside click',()=>{
  const h=harness(),a=h.target('a'),b=h.target('b');
  h.dispatch('pointerover',a);h.tick(549);assert.equal(h.panel.hidden,true);
  h.dispatch('pointerout',a,h.blank);h.tick(1000);assert.equal(h.panel.hidden,true);
  h.dispatch('pointerover',a);h.tick(550);assert.equal(h.panel.innerHTML,'A');assert.equal(h.panel.hidden,false);
  h.dispatch('pointerout',a,b);h.dispatch('pointerover',b,a);h.tick(550);assert.equal(h.panel.innerHTML,'B');assert.equal(h.panel.hidden,false);
  h.dispatch('click',b);h.dispatch('pointerout',b,a);h.dispatch('pointerover',a,b);h.tick(1000);assert.equal(h.panel.innerHTML,'B');assert.equal(h.panel.hidden,false);
  h.dispatch('click',h.blank);assert.equal(h.panel.hidden,true);
});
