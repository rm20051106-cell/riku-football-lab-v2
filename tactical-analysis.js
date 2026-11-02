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
 renderTacticalGrowthGraph();
 renderTacticalMatchReports();
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


function renderTacticalGrowthGraph(){
 const videoView=document.getElementById('video');if(!videoView)return;
 let host=document.getElementById('tacticalGrowthGraph');
 if(!host){host=document.createElement('section');host.id='tacticalGrowthGraph';host.className='card';}
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 const dates={};
 const metrics=[
  {id:'scan',label:'周囲の確認',color:'#78c8ff',score:v=>({'確認したが首振りなし':0,'左右を確認':60,'前方を確認':60,'複数方向を確認':100}[v]??null)},
  {id:'position',label:'立ち位置',color:'#c8f169',score:v=>({'味方と位置が重なる':0,'相手の前':50,'相手と相手の間':100,'相手の背後':100,'外側のスペース':100}[v]??null)},
  {id:'support',label:'サポート角度',color:'#ffbd69',score:v=>({'パスコースを作れていない':0,'真後ろ':0,'横方向':50,'前方斜め':100,'後方斜め':100}[v]??null)},
  {id:'movement',label:'スペースへの動き',color:'#d6a8ff',score:v=>({'動き出しなし':0,'足元に受けに来た':50,'スペースへ動いた':100,'相手を引きつけた':100}[v]??null)}
 ];
 const choices=['パス','ドリブル','シュート','キープ','その他'];
 matches.forEach(match=>(match.candidateEvents||[]).forEach(ev=>{
  if(ev.reviewLabel!=='陸玖'||!ev.tacticalReview?.fields)return;
  const f=ev.tacticalReview.fields;
  const date=String(ev.tacticalReview.reviewedAt||match.date||'日付不明').slice(0,10);
  const row=dates[date]||(dates[date]={date,values:{},counts:{},decision:{}});
  metrics.forEach(m=>{const score=m.score(f[m.id]);if(score===null)return;const a=row.values[m.id]||(row.values[m.id]=[]);a.push(score);row.counts[m.id]=(row.counts[m.id]||0)+1;});
  if(choices.includes(f.decision))row.decision[f.decision]=(row.decision[f.decision]||0)+1;
 }));
 const rows=Object.values(dates).sort((a,b)=>a.date.localeCompare(b.date));
 const decisionRows=rows.filter(r=>Object.values(r.decision).some(Boolean));
 const decisionHtml=decisionRows.length?'<div class="tiny muted" style="margin-top:12px"><b>プレー選択の記録数（評価点ではありません）</b></div>'+decisionRows.map(r=>'<div class="tiny">'+escT(r.date)+'：'+choices.filter(c=>r.decision[c]).map(c=>c+' '+r.decision[c]+'件').join(' ／ ')+'</div>').join(''):'<div class="tiny muted">プレー選択の記録はまだありません。</div>';
 const eligible=metrics.map(m=>({metric:m,points:rows.map(r=>({date:r.date,score:r.values[m.id]?.length?r.values[m.id].reduce((a,b)=>a+b,0)/r.values[m.id].length:null,count:r.counts[m.id]||0})).filter(p=>p.score!==null)}));
 const width=720,height=270,left=48,right=18,top=18,bottom=48,plotW=width-left-right,plotH=height-top-bottom;
 const x=i=>left+(rows.length<=1?plotW/2:i*plotW/(rows.length-1));
 const y=v=>top+(100-v)*plotH/100;
 const grid=[0,25,50,75,100].map(v=>'<line x1="'+left+'" y1="'+y(v)+'" x2="'+(width-right)+'" y2="'+y(v)+'" stroke="#34475f" stroke-width="1"/><text x="'+(left-10)+'" y="'+(y(v)+4)+'" fill="#9fb0c5" font-size="11" text-anchor="end">'+v+'</text>').join('');
 const lineSeries=eligible.map(({metric,points})=>{
  if(points.length<3||new Set(points.map(p=>p.date)).size<2)return '';
  const path=points.map(p=>{const idx=rows.findIndex(r=>r.date===p.date);return (idx===0?'M':'L')+x(idx).toFixed(1)+','+y(p.score).toFixed(1)}).join(' ');
  return '<path d="'+path+'" fill="none" stroke="'+metric.color+'" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'+points.map(p=>{const idx=rows.findIndex(r=>r.date===p.date);return '<circle cx="'+x(idx)+'" cy="'+y(p.score)+'" r="5" fill="'+metric.color+'"><title>'+escT(metric.label)+' '+escT(p.date)+'：'+p.score.toFixed(0)+'点（'+p.count+'件）</title></circle>'}).join('');
 }).join('');
 const xLabels=rows.map((r,i)=>'<text x="'+x(i)+'" y="'+(height-18)+'" fill="#9fb0c5" font-size="10" text-anchor="middle">'+escT(r.date.length>5?r.date.slice(5):r.date)+'</text>').join('');
 const legend=eligible.map(({metric,points})=>{
  const ok=points.length>=3&&new Set(points.map(p=>p.date)).size>=2;
  return '<div class="tiny" style="display:inline-flex;align-items:center;gap:5px;margin:3px 12px 3px 0"><span style="display:inline-block;width:15px;height:4px;background:'+metric.color+';border-radius:4px"></span>'+escT(metric.label)+'：'+(ok?'評価中':'評価保留（'+points.length+'件）')+'</div>';
 }).join('');
 const detail=eligible.map(({metric,points})=>{
  const ok=points.length>=3&&new Set(points.map(p=>p.date)).size>=2;
  if(!ok)return '<div class="listitem"><div class="grow"><b>'+escT(metric.label)+'</b><div class="tiny muted">評価保留：有効な手動確認が3件以上、かつ2日以上の記録が必要です。現在 '+points.length+'件／'+new Set(points.map(p=>p.date)).size+'日</div></div></div>';
  const first=points[0],last=points[points.length-1],diff=last.score-first.score;
  return '<div class="listitem"><div class="grow"><b>'+escT(metric.label)+'</b><div class="tiny muted">初回 '+first.score.toFixed(0)+'点 → 最新 '+last.score.toFixed(0)+'点（'+(diff>0?'+':'')+diff.toFixed(0)+'点）・最新 '+last.count+'場面</div></div></div>';
 }).join('');
 host.innerHTML='<h2>⑦ 陸玖の判断力・ポジショニング成長グラフ</h2><p class="tiny muted">陸玖本人として確認し、手動保存した場面だけを集計。日ごとの平均を時系列で比較します。映像で確認できない項目・未選択項目は除外します。</p><div class="tiny muted">点数は記録上の行動を見える化する目安（0〜100）で、プレーの正解率や選手としての総合評価ではありません。</div><div style="overflow-x:auto;margin-top:10px"><svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="周囲の確認、立ち位置、サポート角度、スペースへの動きの時系列グラフ" style="width:100%;min-width:320px;height:auto">'+grid+lineSeries+xLabels+'</svg></div><div>'+legend+'</div>'+detail+decisionHtml+'<div class="tiny muted" style="margin-top:10px">評価開始条件：各項目で有効な確認が3場面以上、かつ2日以上。プレー選択は状況や味方・相手の位置で正解が変わるため、選択肢の件数だけを表示し、良否の点数にはしません。</div>';
 const tactical=document.getElementById(PANEL_ID);
 if(tactical)tactical.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
}


function renderTacticalMatchReports(){
 const videoView=document.getElementById('video');if(!videoView)return;
 let host=document.getElementById('tacticalMatchReports');
 if(!host){host=document.createElement('section');host.id='tacticalMatchReports';host.className='card';}
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 const reportMatches=matches.map(match=>{
  const scenes=(match.candidateEvents||[]).filter(ev=>ev.reviewLabel==='陸玖'&&ev.tacticalReview?.reviewedAt&&ev.tacticalReview?.fields);
  return {match,scenes};
 }).filter(x=>x.scenes.length);
 const labels={scan:'受ける前の周囲確認',orientation:'受ける時の身体の向き',position:'立ち位置',support:'サポート角度',movement:'スペースへの動き出し'};
 const rules=[
  {id:'scan',good:['左右を確認','前方を確認','複数方向を確認'],weak:['確認したが首振りなし'],goodText:'受ける前に周囲を確認',weakText:'受ける前の確認を増やす',goal:'パスが出る前に左右・前方を見てから受ける'},
  {id:'orientation',good:['前向き','半身'],weak:['後ろ向き'],goodText:'前向き・半身で受けた',weakText:'半身で受ける準備をする',goal:'身体を半身にして前方を見ながら受ける'},
  {id:'position',good:['相手と相手の間','相手の背後','外側のスペース'],weak:['味方と位置が重なる'],goodText:'相手の間・背後・外側に立てた',weakText:'味方と違うレーンを取る',goal:'味方と位置が重ならない別のレーンへ移動する'},
  {id:'support',good:['前方斜め','横方向','後方斜め'],weak:['真後ろ','パスコースを作れていない'],goodText:'斜め・横のパスコースを作れた',weakText:'保持者から角度をつけてサポートする',goal:'保持者の真後ろを避け、斜めのパスコースを作る'},
  {id:'movement',good:['スペースへ動いた','相手を引きつけた'],weak:['動き出しなし'],goodText:'スペースへ動く・相手を引きつけた',weakText:'空いた場所への動き出しを増やす',goal:'味方が顔を上げる前に空いたスペースへ動き出す'}
 ];
 const reports=reportMatches.map(({match,scenes})=>{
  const enough=scenes.length>=3;
  const facts=rules.map(rule=>{
   const observed=scenes.filter(ev=>{const v=ev.tacticalReview.fields[rule.id];return v&&v!=='映像で確認できない'&&!String(v).includes('不明');});
   const good=observed.filter(ev=>rule.good.includes(ev.tacticalReview.fields[rule.id])).length;
   const weak=observed.filter(ev=>rule.weak.includes(ev.tacticalReview.fields[rule.id])).length;
   return {...rule,observed:observed.length,good,weak};
  });
  const strengths=facts.filter(x=>x.observed>=2&&x.good>=2&&x.good>x.weak).sort((a,b)=>b.good-a.good);
  const weaknesses=facts.filter(x=>x.observed>=2&&x.weak>=2&&x.weak>=x.good).sort((a,b)=>b.weak-a.weak);
  const goals=[];
  weaknesses.forEach(x=>{if(goals.length<3)goals.push({text:x.goal,source:x.weak+'場面で確認',status:'改善テーマ'});});
  strengths.forEach(x=>{if(goals.length<3)goals.push({text:x.goal.replace('受ける','受ける動き')+'を次の試合でも再現する',source:x.good+'場面で確認',status:'継続目標'});});
  while(goals.length<3)goals.push({text:'次の試合でも受ける前・受ける瞬間・受けた後を撮影し、'+(goals.length===0?'周囲の確認':goals.length===1?'立ち位置':'サポートと動き出し')+'を確認する',source:'この項目はまだ十分な傾向がありません',status:'観察目標・評価保留'});
  const outcomeCounts={};
  scenes.forEach(ev=>{const f=ev.tacticalReview.fields;if(f.decision&&f.decision!=='映像で確認できない'&&f.outcome&&f.outcome!=='映像で確認できない'){const key=f.decision+' → '+f.outcome;outcomeCounts[key]=(outcomeCounts[key]||0)+1;}});
  const outcomeHtml=Object.keys(outcomeCounts).length?'<div class="tiny muted"><b>選択と結果の記録（良否の判定ではありません）</b></div>'+Object.entries(outcomeCounts).sort((a,b)=>b[1]-a[1]).map(([k,n])=>'<div class="tiny">'+escT(k)+'：'+n+'件</div>').join(''):'<div class="tiny muted">選択と結果の両方が確認できた場面はありません。</div>';
  const factHtml=facts.map(x=>'<div class="listitem"><div class="grow"><b>'+escT(labels[x.id])+'</b><div class="tiny muted">'+(enough?'確認できた '+x.observed+'場面｜良い行動 '+x.good+'件｜改善サイン '+x.weak+'件':'評価保留：試合内の本人確認済み場面が3件未満（'+scenes.length+'件）')+'</div></div></div>').join('');
  const sceneHtml=scenes.map(ev=>{
   const f=ev.tacticalReview.fields;
   const time=typeof formatMatchTime==='function'?formatMatchTime(ev.time):ev.time;
   const picked=rules.filter(r=>f[r.id]&&f[r.id]!=='映像で確認できない').map(r=>labels[r.id]+'：'+f[r.id]);
   const choice=f.decision&&f.decision!=='映像で確認できない'?'選択 '+f.decision:'選択 評価保留';
   const outcome=f.outcome&&f.outcome!=='映像で確認できない'?'結果 '+f.outcome:'結果 評価保留';
   return '<div class="tiny" style="padding:7px 0;border-bottom:1px solid #29384b"><b>'+escT(time)+'｜'+escT(ev.actionType||ev.label||'確認場面')+'</b><div>'+escT(picked.join('／')||'行動項目は評価保留')+'</div><div class="muted">'+escT(choice)+'｜'+escT(outcome)+'</div></div>';
  }).join('');
  return {match,scenes,enough,strengths,weaknesses,goals,factHtml,outcomeHtml,sceneHtml};
 });
 const content=reports.length?reports.map((r,i)=>{
  const title=(r.match.date||'日付不明')+'｜'+(r.match.title||'試合動画');
  const strengths=r.enough&&r.strengths.length?r.strengths.map(x=>'<div class="tiny">・'+escT(x.goodText)+'（'+x.good+'場面）</div>').join(''):'<div class="tiny muted">評価保留：良かった判断の傾向を示すには、同じ項目で複数場面の確認が必要です。</div>';
  const weaknesses=r.enough&&r.weaknesses.length?r.weaknesses.map(x=>'<div class="tiny">・'+escT(x.weakText)+'（'+x.weak+'場面）</div>').join(''):'<div class="tiny muted">評価保留：苦手な状況と断定できる繰り返しの記録はありません。</div>';
  const goals=r.goals.map((g,j)=>'<div class="listitem"><div class="grow"><b>目標 '+(j+1)+'｜'+escT(g.text)+'</b><div class="tiny muted">'+escT(g.status)+'・'+escT(g.source)+'</div></div></div>').join('');
  const strengthsBlock=r.enough?strengths:'<div class="tiny muted">評価保留：本人確認済み場面が3件以上になると傾向を表示します。</div>';
  const weaknessesBlock=r.enough?weaknesses:'<div class="tiny muted">評価保留：本人確認済み場面が3件以上になると傾向を表示します。</div>';
  return '<div class="card" style="margin-top:12px"><h3>'+escT(title)+'</h3><div class="tiny muted">手動確認済み '+r.scenes.length+'場面'+(r.enough?'':'｜評価保留：3場面以上必要')+'</div><div class="divider"></div><b>良かった判断・行動</b>'+strengthsBlock+'<div style="margin-top:10px"><b>改善したい判断・行動</b>'+weaknessesBlock+'</div><div style="margin-top:10px"><b>得意な状況</b>'+(r.enough?strengths:'<div class="tiny muted">評価保留</div>')+'<div style="margin-top:10px"><b>苦手な状況</b>'+(r.enough?weaknesses:'<div class="tiny muted">評価保留</div>')+'<div style="margin-top:10px"><b>次の試合の目標3つ</b>'+goals+'<div style="margin-top:10px">'+r.outcomeHtml+'</div><details style="margin-top:10px"><summary class="tiny">確認した場面の内訳を見る</summary>'+r.sceneHtml+'</details><div class="tiny muted" style="margin-top:10px">判断の良否は映像状況全体を見ずに断定しません。ここでは手動入力された行動傾向と、選択・結果の記録を分けて表示しています。</div></div>';
 }).join(''):'<div class="empty">手動確認済みの試合場面がまだありません。試合分析で陸玖本人として確認し、各場面の判断・ポジショニングを保存するとレポートが作成されます。</div>';
 host.innerHTML='<h2>⑧ 試合別・場面別の改善レポート</h2><p class="tiny muted">試合ごとに、陸玖本人として確認し、手動保存した場面だけを集計します。映像で確認できない項目は評価から除外します。</p>'+content;
 const graph=document.getElementById('tacticalGrowthGraph');
 const tactical=document.getElementById(PANEL_ID);
 if(graph)graph.insertAdjacentElement('afterend',host);else if(tactical)tactical.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
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