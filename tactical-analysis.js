(function(){
'use strict';
const PANEL_ID='rikuTacticalAnalysisPanel';
let selectedMatchId='';
let selectedEventId='';
const escT=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fields=[
 {id:'scan',label:'受ける前の首振り・周囲確認',options:['映像で確認できない','確認したが首振りなし','左右を確認','前方を確認','複数方向を確認']},
 {id:'orientation',label:'ボールを受ける時の身体の向き',options:['映像で確認できない','前向き','半身','後ろ向き','相手・味方に隠れて不明']},
 {id:'position',label:'立ち位置・相手との関係',options:['映像で確認できない','相手と相手の間','相手の背後','相手の前','外側のスペース','味方と位置が重なる']},
 {id:'support',label:'味方を助けるサポート角度',options:['映像で確認できない','前方斜め','横方向','後方斜め','真後ろ','パスコースを作れていない']},
 {id:'movement',label:'スペースへの動き出し',options:['映像で確認できない','スペースへ動いた','足元に受けに来た','相手を引きつけた','動き出しなし']},
 {id:'decision',label:'その場面で選べたプレー',options:['映像で確認できない','パス','ドリブル','シュート','キープ','その他']},
 {id:'outcome',label:'実際のプレー結果',options:['映像で確認できない','前進できた','味方につながった','シュートにつながった','ボールを失った','チャンスを作れた']}
];
function getData(){
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 return matches.filter(m=>(m.candidateEvents||[]).some(e=>e.reviewLabel==='陸玖'));
}
function getSelected(){
 const matches=getData();
 let match=matches.find(m=>String(m.id)===String(selectedMatchId))||matches[0]||null;
 if(match)selectedMatchId=String(match.id);
 const events=(match?.candidateEvents||[]).filter(e=>e.reviewLabel==='陸玖');
 let ev=events.find(e=>String(e.id)===String(selectedEventId))||events[0]||null;
 if(ev)selectedEventId=String(ev.id);
 return {match,ev,events};
}
function adviceFor(f){
 const out=[];
 if(f.scan==='映像で確認できない')out.push('首振り：この映像では確認できません。受ける直前の顔・上半身が見える場面で再確認します。');
 else if(f.scan==='確認したが首振りなし')out.push('首振り：受ける直前に左右・前方を一度確認してから受ける練習をします。');
 if(f.orientation==='後ろ向き')out.push('身体の向き：背中を向けたまま受ける場面。半身で受け、次のプレー方向を作れるか確認します。');
 if(f.position==='味方と位置が重なる')out.push('立ち位置：味方と同じ場所に集まりやすい場面。少し幅を取り、別のパスコースを作ることを試します。');
 if(f.support==='真後ろ'||f.support==='パスコースを作れていない')out.push('サポート角度：保持者の真後ろを避け、斜め前・斜め後ろに立ってパスコースを作れるか試します。');
 if(f.movement==='動き出しなし')out.push('動き出し：ボール保持者だけを見ず、相手の背後や空いた場所へ動くタイミングを確認します。');
 if(f.movement==='足元に受けに来た')out.push('動き出し：足元で受ける選択だけでなく、相手の背後や横のスペースへ動く選択も比べます。');
 if(f.decision==='映像で確認できない'||f.outcome==='映像で確認できない')out.push('判断：周囲の選手・ボール・ゴールが映っていないため、選択肢や結果は断定しません。');
 if(!out.length)out.push('今回の確認項目では大きな改善指示を決めきれません。別の角度や前後数秒も見て、同じ判断を再現できるか確認します。');
 return out;
}
function selectHtml(f,v){
 return '<label class="label">'+escT(f.label)+'<select data-tactical-field="'+f.id+'">'+f.options.map(x=>'<option value="'+escT(x)+'"'+(x===v?' selected':'')+'>'+escT(x)+'</option>').join('')+'</select></label>';
}
function render(){
 let host=document.getElementById(PANEL_ID);
 if(!host){
  const history=document.getElementById('matchScanRecords');
  const anchor=history?.closest('.card');
  const videoView=document.getElementById('video');
  if(!videoView)return;
  host=document.createElement('div');host.id=PANEL_ID;host.className='card';
  if(anchor)anchor.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
 }
 const matches=getData();
 if(!matches.length){
  host.innerHTML='<h2>⑥ 試合中の判断・ポジショニング分析</h2><p class="tiny muted">保存した試合スキャンから「陸玖本人」と手動確認した場面を選び、プレー前後の状況を記録します。</p><div class="note">まだ対象場面がありません。先にAI試合スキャン履歴で場面を開き、映像を確認して「陸玖本人」として保存してください。</div>';
  return;
 }
 const chosen=getSelected();
 const match=chosen.match,ev=chosen.ev;
 if(!ev){host.innerHTML='<h2>⑥ 試合中の判断・ポジショニング分析</h2><div class="empty">本人確認済みの場面がありません。</div>';return;}
 const review=ev.tacticalReview||{};
 const f=review.fields||{};
 const matchOptions=matches.map(m=>'<option value="'+escT(m.id)+'"'+(String(m.id)===String(match.id)?' selected':'')+'>'+escT(m.date||'日付不明')+'｜'+escT(m.title||'試合動画')+'</option>').join('');
 const eventOptions=chosen.events.map(e=>'<option value="'+escT(e.id)+'"'+(String(e.id)===String(ev.id)?' selected':'')+'>'+escT(typeof formatMatchTime==='function'?formatMatchTime(e.time):e.time)+'｜'+escT(e.actionType||e.label||'場面候補')+'</option>').join('');
 const reviewHtml=fields.map(x=>selectHtml(x,f[x.id]||'映像で確認できない')).join('');
 const notes=adviceFor(f);
 const saved=review.reviewedAt?'<div class="note success">保存済み：'+escT(review.reviewedAt)+'｜この内容は手動確認した記録です。</div>':'<div class="tiny muted">まだ分析内容は保存されていません。</div>';
 host.innerHTML='<h2>⑥ 試合中の判断・ポジショニング分析</h2><p class="tiny muted">本人確認済みの場面を使い、受ける前→受ける瞬間→次のプレーまでを確認。映像で見えない項目は「映像で確認できない」のまま保存できます。</p><label class="label">試合を選択<select id="tacticalMatchSelect">'+matchOptions+'</select></label><label class="label">陸玖本人として確認した場面<select id="tacticalEventSelect">'+eventOptions+'</select></label><div class="tiny muted">場面時刻：'+escT(typeof formatMatchTime==='function'?formatMatchTime(ev.time):ev.time)+'｜'+escT(ev.label||ev.reason||'動きの変化候補')+'</div><div class="divider"></div>'+reviewHtml+'<label class="label">映像で確認した状況・味方や相手の位置など<textarea id="tacticalNote" maxlength="600" rows="3" placeholder="例：左前方に味方、正面に相手。右側に空いたスペースがあった">'+escT(review.note||'')+'</textarea></label><div class="btnrow"><button id="tacticalSaveButton">この場面の分析を保存</button><button type="button" class="secondary" id="tacticalClearButton">入力をリセット</button></div><div id="tacticalSavedState">'+saved+'</div><div id="tacticalAdvice" class="card" style="margin-top:12px"><h3>確認内容からの次の意識</h3>'+notes.map(x=>'<div class="listitem"><div class="grow">'+escT(x)+'</div></div>').join('')+'<div class="tiny muted">これは入力した手動確認内容に基づく練習候補です。AIが映像から首振り・味方や相手の位置・最適判断を自動認識した結果ではありません。</div></div>';
 const matchSelect=document.getElementById('tacticalMatchSelect');
 const eventSelect=document.getElementById('tacticalEventSelect');
 matchSelect.onchange=()=>{selectedMatchId=matchSelect.value;selectedEventId='';render();};
 eventSelect.onchange=()=>{selectedEventId=eventSelect.value;render();};
 document.getElementById('tacticalSaveButton').onclick=()=>{
  const current=getSelected();if(!current.match||!current.ev||current.ev.reviewLabel!=='陸玖'){alert('陸玖本人として確認済みの場面だけ保存できます。');return;}
  const values={};fields.forEach(x=>{values[x.id]=host.querySelector('[data-tactical-field="'+x.id+'"]')?.value||'映像で確認できない';});
  current.ev.tacticalReview={version:1,reviewedAt:typeof today==='function'?today():new Date().toISOString().slice(0,10),fields:values,note:document.getElementById('tacticalNote').value.trim().slice(0,600)};
  if(typeof persist==='function')persist();
  render();
  alert('試合中の判断・ポジショニング分析を保存しました。');
 };
 document.getElementById('tacticalClearButton').onclick=()=>{
  host.querySelectorAll('[data-tactical-field]').forEach(el=>el.value='映像で確認できない');
  document.getElementById('tacticalNote').value='';
 };
}
function getTacticalWeeklyEvidence(){
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 const evidence=[];
 matches.forEach(match=>(match.candidateEvents||[]).forEach(ev=>{
  if(ev.reviewLabel!=='陸玖'||!ev.tacticalReview?.fields)return;
  const f=ev.tacticalReview.fields;
  const add=(key,focus,reason,drill,score)=>{if(f[key]&&f[key]!=='映像で確認できない')evidence.push({key,focus,reason,drill,score,matchId:match.id,eventId:ev.id,date:match.date||''});};
  if(f.scan==='確認したが首振りなし')add('scan','ボールを受ける','受ける直前の周囲確認が少なかった場面','左右・前方を確認してから半身で受ける練習',5);
  if(f.orientation==='後ろ向き')add('orientation','ボールを受ける','後ろ向きで受けた場面','半身で受け、前方へファーストタッチする練習',4);
  if(f.position==='味方と位置が重なる')add('position','オフザボール','味方と立ち位置が重なった場面','味方と違うレーンへ移動してパスコースを作る練習',5);
  if(f.support==='真後ろ'||f.support==='パスコースを作れていない')add('support','オフザボール','サポート角度を作りにくかった場面','保持者の斜め前・斜め後ろに立つ角度づくり',5);
  if(f.movement==='動き出しなし')add('movement','オフザボール','スペースへの動き出しが見られなかった場面','味方が顔を上げる前に斜め・背後へ動く練習',5);
  if(f.movement==='足元に受けに来た')add('movement','オフザボール','足元へ受けに来た場面','足元と背後への動き出しを使い分ける練習',3);
 }));
 const groups={};
 evidence.forEach(x=>{const g=groups[x.key]||(groups[x.key]={...x,count:0,latest:x.date});g.count++;if(String(x.date)>String(g.latest))g.latest=x.date;});
 return Object.values(groups).sort((a,b)=>b.score*b.count-a.score*a.count||String(b.latest).localeCompare(String(a.latest)));
}
function getTacticalWeeklyPriority(){
 const rows=getTacticalWeeklyEvidence();
 return rows.length?rows[0]:null;
}
function applyTacticalWeeklyPlan(plans){
 const rows=getTacticalWeeklyEvidence();
 if(!rows.length)return plans;
 const chosen=rows.slice(0,3);
 const templates={
 'ボールを受ける':{title:'首振り＋半身で前向きに受ける',category:'受ける動き',minutes:12,note:'パスが出る前に左右・前方を確認。半身で受け、前へ運べるファーストタッチを左右から反復する。'},
 'オフザボール':{title:'サポート角度＋スペースへの動き出し',category:'受ける動き',minutes:12,note:'保持者の斜め前・斜め後ろに立つ。味方が顔を上げる前に、相手の背後や空いたレーンへ動く。'}
 };
 const unique=[];
 chosen.forEach(x=>{if(!unique.some(y=>y.focus===x.focus))unique.push(x);});
 const slots=[0,2,1];
 unique.slice(0,3).forEach((e,i)=>{
  const template=templates[e.focus];if(!template)return;
  const idx=slots[i];
  const base=plans[idx];
  plans[idx]={...base,title:template.title,category:template.category,focus:e.focus,minutes:template.minutes,note:template.note+'\\n\\n【試合映像からの改善テーマ】'+e.reason+'。'+e.drill,why:'本人確認済みの試合場面 '+e.count+'件を反映：'+e.reason};
 });
 return plans;
}
function renderTacticalWeeklyEvidence(){
 const host=typeof dailyPlan!=='undefined'?dailyPlan:null;if(!host)return;
 const priority=getTacticalWeeklyPriority();if(!priority)return;
 if(document.getElementById('tacticalWeeklyEvidence'))return;
 const box=document.createElement('div');box.id='tacticalWeeklyEvidence';box.className='note';box.style.marginTop='12px';
 box.innerHTML='<b>試合分析を反映した翌週の重点テーマ</b><div class="tiny">本人確認済み・手動分析済み '+getTacticalWeeklyEvidence().reduce((n,x)=>n+x.count,0)+'項目を集計</div>'+getTacticalWeeklyEvidence().slice(0,3).map(x=>'<div class="listitem"><div class="grow"><b>'+escT(x.focus)+'｜'+escT(x.reason)+'</b><div class="tiny muted">'+x.count+'件・'+escT(x.drill)+'</div></div></div>').join('')+'<div class="tiny muted">映像で確認できない項目は集計から除外。手動確認の記録から練習候補を作成しています。</div>';
 host.appendChild(box);
}
function installWeeklyCoach(){
 if(typeof window.getWeeklyCoachPlan==='function'&&!window.getWeeklyCoachPlan.__tacticalWeekWrapped){
  const original=window.getWeeklyCoachPlan;
  const wrapped=function(){return applyTacticalWeeklyPlan(original.apply(this,arguments));};
  wrapped.__tacticalWeekWrapped=true;window.getWeeklyCoachPlan=wrapped;
 }
 if(typeof window.renderAll==='function'&&!window.renderAll.__tacticalWeekRenderWrapped){
  const original=window.renderAll;
  const wrapped=function(){const result=original.apply(this,arguments);renderTacticalWeeklyEvidence();return result;};
  wrapped.__tacticalWeekRenderWrapped=true;window.renderAll=wrapped;
 }
 renderTacticalWeeklyEvidence();
}

function install(){
 if(typeof state==='undefined')return;
 render();
 installWeeklyCoach();
 if(typeof window.renderAll==='function'&&!window.renderAll.__tacticalWrapped){
  const original=window.renderAll;
  const wrapped=function(){const result=original.apply(this,arguments);render();return result;};
  wrapped.__tacticalWrapped=true;window.renderAll=wrapped;
 }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuTacticalAnalysis=render;
})();