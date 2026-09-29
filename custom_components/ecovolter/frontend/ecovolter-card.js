
const VERSION="0.2.0-beta.1-dev22";
async function devices(h){return (await h.callWS({type:"config/device_registry/list"})).filter(d=>(d.identifiers||[]).some(i=>Array.isArray(i)&&i[0]==="ecovolter"))}
async function entities(h,id){return (await h.callWS({type:"config/entity_registry/list"})).filter(e=>e.device_id===id&&!e.disabled_by)}
function key(u){for(const k of ["vehicle_connected","charging","power","session_energy","total_energy","charging_count","total_charging_time","current_l1","current_l2","current_l3","voltage_l1","voltage_l2","voltage_l3","active_phases","configured_current","charging_enabled","three_phase","target_current"])if((u||"").endsWith("_"+k))return k}
class EcoVolterCard extends HTMLElement{
 static getConfigElement(){return document.createElement("ecovolter-card-editor")}
 static getStubConfig(){return {variant:"compact",language:"cs"}}
 setConfig(c){this.c={variant:"compact",language:"cs",...c};this.sliderValue=null;this.draw()}
 set hass(h){
  this.h=h;
  // Do not rebuild the DOM while the user is dragging the range control.
  // A coordinator update would otherwise recreate the slider and snap it
  // back to the last HA state before the finger/mouse reaches the target.
  if(this.sliderActive)return;
  this.resolve();
 }
 getCardSize(){return this.c?.variant==="detailed"?10:6}
 async resolve(){if(!this.h||!this.c?.device)return this.draw();if(this.did===this.c.device&&this.e)return this.draw();this.did=this.c.device;this.e={};for(const x of await entities(this.h,this.c.device)){const k=key(x.unique_id);if(k)this.e[k]=x.entity_id}this.draw()}
 s(k){return this.e?.[k]?this.h?.states?.[this.e[k]]:null}
 v(k){
  const s=this.s(k); if(!s||["unknown","unavailable"].includes(s.state))return "—";
  const n=Number(s.state);
  if(k==="total_charging_time"&&Number.isFinite(n)){const m=Math.round(n/60),h=Math.floor(m/60);return h+" h "+(m%60)+" min"}
  if((k==="charging_count"||k==="active_phases")&&Number.isFinite(n))return String(Math.round(n));
  if(Number.isFinite(n))return n.toFixed(2)+(s.attributes.unit_of_measurement?" "+s.attributes.unit_of_measurement:"");
  return s.state+(s.attributes.unit_of_measurement?" "+s.attributes.unit_of_measurement:"");
 }
 async toggle(k){
  const s=this.s(k); if(!s||!["on","off"].includes(s.state))return;
  const service=s.state==="on"?"turn_off":"turn_on";
  await this.h.callService("switch",service,{entity_id:s.entity_id});
 }
 current(e){const s=this.s("target_current");if(s)this.h.callService("number","set_value",{entity_id:s.entity_id,value:Number(e.target.value)})}
  draw(){
  if(!this.c)return;
  if(!this.c.device){const msg=this.c.language==="en"?"Select an EcoVolter charger in the card editor.":"Vyberte EcoVolter nabíječku v editoru karty.";this.innerHTML='<ha-card><div style="padding:18px">'+msg+'</div></ha-card>';return}
  if(!this.h||!this.e)return;
  const on=this.s("charging_enabled")?.state==="on",three=this.s("three_phase")?.state==="on",connected=this.s("vehicle_connected")?.state==="on",charging=this.s("charging")?.state==="on",actualAmp=this.s("target_current")?.state||6,amp=this.sliderValue??actualAmp;
  const en=this.c.language==="en";
  const t=en?{connected:"🟢 Vehicle connected",disconnected:"⚪ Vehicle disconnected",charging:"charging",idle:"not charging",power:"Power",session:"Session",phases:"Phases",configured:"Charging current",charge:"Charging",phase:"3 phases",current:"Current",phaseCurrents:"Phase currents",phaseVoltages:"Phase voltages",stats:"Statistics",total:"Total",count:"Charging count",duration:"Duration"}:{connected:"🟢 Vozidlo připojeno",disconnected:"⚪ Vozidlo nepřipojeno",charging:"nabíjí",idle:"nenabíjí",power:"Výkon",session:"Relace",phases:"Fáze",configured:"Nabíjecí proud",charge:"Nabíjení",phase:"3 fáze",current:"Proud",phaseCurrents:"Proudy fází",phaseVoltages:"Napětí fází",stats:"Statistiky",total:"Celkem",count:"Počet nabíjení",duration:"Doba"};
  let detail="";
  if(this.c.variant==="detailed")detail='<div class="section"><b>'+t.phaseCurrents+'</b></div><div class="phase-grid">'+["current_l1","current_l2","current_l3"].map((k,n)=>'<div><small>L'+(n+1)+'</small><strong>'+this.v(k)+'</strong></div>').join("")+'</div><div class="section"><b>'+t.phaseVoltages+'</b></div><div class="phase-grid">'+["voltage_l1","voltage_l2","voltage_l3"].map((k,n)=>'<div><small>L'+(n+1)+'</small><strong>'+this.v(k)+'</strong></div>').join("")+'</div><div class="section"><b>'+t.stats+'</b></div><div class="phase-grid"><div><small>'+t.total+'</small><strong>'+this.v("total_energy")+'</strong></div><div><small>'+t.count+'</small><strong>'+this.v("charging_count")+'</strong></div><div><small>'+t.duration+'</small><strong>'+this.v("total_charging_time")+'</strong></div></div>';
  this.innerHTML='<style>:host{display:block;box-sizing:border-box;min-width:0}ha-card{display:block;box-sizing:border-box;width:100%;height:auto;overflow:hidden;padding:16px}.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.title{font-size:20px;font-weight:600}.status{font-size:13px;opacity:.7}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.grid>div,.phase-grid>div{min-width:0;padding:10px;text-align:center;border-radius:12px;background:var(--secondary-background-color)}.phase-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}small{display:block;opacity:.65;margin-bottom:4px}strong{font-size:16px}.switches{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}button{border:0;border-radius:12px;padding:12px;background:var(--secondary-background-color);color:var(--primary-text-color)}button.on{background:var(--primary-color);color:var(--text-primary-color)}.slider{display:flex;gap:12px;align-items:center;margin-top:12px}.slider input{flex:1}.section{margin:16px 0 8px}@media(max-width:600px){ha-card{padding:14px}.title{font-size:19px}.grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.grid>div{padding:9px 5px}small{font-size:11px}strong{font-size:15px}.phase-grid{gap:6px}.switches{gap:6px}.switches button{padding:11px 6px;font-size:13px}.slider{gap:8px}.section{margin-top:14px}}</style><ha-card><div class="head"><div><div class="title">'+(this.c.name||"EcoVolter")+'</div><div class="status">'+(connected?t.connected:t.disconnected)+' · '+(charging?t.charging:t.idle)+'</div></div><ha-icon icon="mdi:ev-station"></ha-icon></div><div class="grid"><div><small>'+t.power+'</small><strong>'+this.v("power")+'</strong></div><div><small>'+t.session+'</small><strong>'+this.v("session_energy")+'</strong></div><div><small>'+t.phases+'</small><strong>'+this.v("active_phases")+'</strong></div><div><small>'+t.configured+'</small><strong>'+this.v("configured_current")+'</strong></div></div><div class="switches"><button id="charge" class="'+(on?"on":"")+'">⚡ '+t.charge+' '+(on?"ON":"OFF")+'</button><button id="phase" class="'+(three?"on":"")+'">〰 '+t.phase+' '+(three?"ON":"OFF")+'</button></div><div class="slider"><span>'+t.current+'</span><input id="amp" type="range" min="6" max="16" step="1" value="'+amp+'"><b>'+amp+' A</b></div>'+detail+'</ha-card>';
  this.querySelector("#charge")?.addEventListener("click",()=>this.toggle("charging_enabled"));
  this.querySelector("#phase")?.addEventListener("click",()=>this.toggle("three_phase"));
  const slider=this.querySelector("#amp");
  const ampLabel=this.querySelector(".slider b");
  slider?.addEventListener("pointerdown",()=>{this.sliderActive=true});
  slider?.addEventListener("touchstart",()=>{this.sliderActive=true},{passive:true});
  slider?.addEventListener("input",e=>{this.sliderActive=true;this.sliderValue=e.currentTarget.value;if(ampLabel)ampLabel.textContent=e.currentTarget.value+" A"});
  slider?.addEventListener("change",async e=>{
    const value=e.currentTarget.value;
    this.sliderValue=value;
    this.sliderActive=false;
    if(ampLabel)ampLabel.textContent=value+" A";
    await this.current(e);
    // Keep the requested value visible. The integration owns the value after a
    // successful PATCH and its periodic settings refresh will verify it later.
  });
  slider?.addEventListener("pointercancel",()=>{this.sliderActive=false;this.resolve()})
 }}
class EcoVolterCardEditor extends HTMLElement{
 setConfig(c){this.c={variant:"compact",language:"cs",...c};this.render()}
 set hass(h){this.h=h;if(!this.d&&!this.loading)this.load()}
 async load(){
  if(!this.h||this.loading)return;
  this.loading=true;
  try{this.d=await devices(this.h)}
  finally{this.loading=false}
  this.render();
 }
 fire(k,v){
  if(v==null||this.c?.[k]===v)return;
  this.c={...this.c,[k]:v};
  this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this.c},bubbles:true,composed:true}));
  this.render();
 }
 render(){
  if(!this.c)return;
  const ds=this.d||[];
  this.innerHTML='<style>.w{display:grid;gap:14px}.field{display:grid;gap:6px}.label{font-size:12px;color:var(--secondary-text-color)}select,input{box-sizing:border-box;width:100%;height:48px;padding:0 12px;border:1px solid var(--divider-color);border-radius:4px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit}</style><div class="w"><label class="field"><span class="label">Nabíječka</span><select id="d"><option value="">Vyberte EcoVolter…</option>'+ds.map(d=>'<option value="'+d.id+'" '+(d.id===this.c.device?"selected":"")+'>'+(d.name_by_user||d.name||d.id)+'</option>').join("")+'</select></label><label class="field"><span class="label">Varianta</span><select id="v"><option value="compact" '+(this.c.variant==="compact"?"selected":"")+'>Compact</option><option value="detailed" '+(this.c.variant==="detailed"?"selected":"")+'>Detailed</option></select></label><label class="field"><span class="label">Jazyk / Language</span><select id="l"><option value="cs" '+(this.c.language!=="en"?"selected":"")+'>Čeština</option><option value="en" '+(this.c.language==="en"?"selected":"")+'>English</option></select></label><label class="field"><span class="label">Název</span><input id="n" value="'+(this.c.name||"")+'" placeholder="EcoVolter"></label></div>';
  this.querySelector("#d")?.addEventListener("change",e=>this.fire("device",e.currentTarget.value));
  this.querySelector("#v")?.addEventListener("change",e=>this.fire("variant",e.currentTarget.value));
  this.querySelector("#l")?.addEventListener("change",e=>this.fire("language",e.currentTarget.value));
  this.querySelector("#n")?.addEventListener("change",e=>this.fire("name",e.currentTarget.value));
 }
}
if(!customElements.get("ecovolter-card"))customElements.define("ecovolter-card",EcoVolterCard);
if(!customElements.get("ecovolter-card-editor"))customElements.define("ecovolter-card-editor",EcoVolterCardEditor);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==="ecovolter-card"))window.customCards.push({type:"ecovolter-card",name:"EcoVolter",description:"EcoVolter charger card with device selection",preview:true,documentationURL:"https://github.com/itsit-cz/HA-ecovolter"});
console.info("EcoVolter Card "+VERSION);
