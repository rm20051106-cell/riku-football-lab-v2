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
 {id:'outcome',label:'実際のプレー結果',options:['映像で確認できない','前進できた','味方につながった','シュートにつながった','ボールを失った','チャンスを作れた']},
 {id:'opponentDefense',label:'相手の守備の特徴',options:['映像で確認できない','高い位置から守備','中央を固める守備','サイドへ誘導する守備','最終ラインが低い','1人が対応','複数人で囲む','その他']},
 {id:'pressure',label:'ボールを持った時の相手のプレス',options:['映像で確認できない','強いプレスなし','前からプレス','横から寄せ','後ろから追われる','複数人に囲まれる']},
 {id:'zone',label:'プレーした場所',options:['映像で確認できない','自陣','中盤','敵陣','ペナルティエリア付近']},
 {id:'scoreState',label:'その時の試合状況',options:['映像で確認できない','リード','同点','ビハインド']}
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
 renderTacticalSituationAnalysis();
 renderTacticalDecisionScenarios();
 renderTacticalTrainingLog();
 renderTacticalDecisionGrowthReport();
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
 host.innerHTML='<h2>⑥ 試合中の判断・ポジショニング分析</h2><p class="tiny muted">本人確認済みの場面を使い、受ける前→受ける瞬間→次のプレーまでを確認。映像で見えない項目は「映像で確認できない」のまま保存できます。</p><label class="label">試合を選択<select id="tacticalMatchSelect">'+matchOptions+'</select></label><label class="label">陸玖本人として確認した場面<select id="tacticalEventSelect">'+eventOptions+'</select></label><div class="tiny muted">場面時刻：'+escT(typeof formatMatchTime==='function'?formatMatchTime(ev.time):ev.time)+'｜'+escT(ev.label||ev.reason||'動きの変化候補')+'</div><div class="divider"></div>'+reviewHtml+'<label class="label">相手チーム名（任意）<input id="tacticalOpponentTeam" maxlength="80" value="'+escT(review.context?.opponentTeam||'')+'" placeholder="例：FC〇〇"></label><label class="label">映像で確認した状況・味方や相手の位置など<textarea id="tacticalNote" maxlength="600" rows="3" placeholder="例：左前方に味方、正面に相手。右側に空いたスペースがあった">'+escT(review.note||'')+'</textarea></label><div class="btnrow"><button id="tacticalSaveButton">この場面の分析を保存</button><button type="button" class="secondary" id="tacticalClearButton">入力をリセット</button></div><div id="tacticalSavedState">'+saved+'</div><div id="tacticalAdvice" class="card" style="margin-top:12px"><h3>確認内容からの次の意識</h3>'+notes.map(x=>'<div class="listitem"><div class="grow">'+escT(x)+'</div></div>').join('')+'<div class="tiny muted">これは入力した手動確認内容に基づく練習候補です。AIが映像から首振り・味方や相手の位置・最適判断を自動認識した結果ではありません。</div></div>';
 const matchSelect=document.getElementById('tacticalMatchSelect');
 const eventSelect=document.getElementById('tacticalEventSelect');
 matchSelect.onchange=()=>{selectedMatchId=matchSelect.value;selectedEventId='';render();};
 eventSelect.onchange=()=>{selectedEventId=eventSelect.value;render();};
 document.getElementById('tacticalSaveButton').onclick=()=>{
  const current=getSelected();if(!current.match||!current.ev||current.ev.reviewLabel!=='陸玖'){alert('陸玖本人として確認済みの場面だけ保存できます。');return;}
  const values={};fields.forEach(x=>{values[x.id]=host.querySelector('[data-tactical-field="'+x.id+'"]')?.value||'映像で確認できない';});
  const previousContext=current.ev.tacticalReview?.context||{};
  const opponentTeam=(document.getElementById('tacticalOpponentTeam')?.value||'').trim().slice(0,80);
  current.ev.tacticalReview={version:2,reviewedAt:typeof today==='function'?today():new Date().toISOString().slice(0,10),fields:values,context:{...previousContext,opponentTeam},note:document.getElementById('tacticalNote').value.trim().slice(0,600)};
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
 return applyTacticalDecisionTrainingPlan(plans);
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
  if(enough)weaknesses.forEach(x=>{if(goals.length<3)goals.push({text:x.goal,source:x.weak+'場面で確認',status:'改善テーマ'});});
  if(enough)strengths.forEach(x=>{if(goals.length<3)goals.push({text:x.goal.replace('受ける','受ける動き')+'を次の試合でも再現する',source:x.good+'場面で確認',status:'継続目標'});});
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


function renderTacticalSituationAnalysis(){
 const videoView=document.getElementById('video');if(!videoView)return;
 let host=document.getElementById('tacticalSituationAnalysis');
 if(!host){host=document.createElement('section');host.id='tacticalSituationAnalysis';host.className='card';}
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 const scenes=[];
 matches.forEach(match=>(match.candidateEvents||[]).forEach(ev=>{
  const review=ev.tacticalReview;
  if(ev.reviewLabel!=='陸玖'||!review?.reviewedAt||!review.fields)return;
  scenes.push({match,ev,review,fields:review.fields,opponent:String(review.context?.opponentTeam||'').trim()});
 }));
 const dimensions=[
  {id:'opponentDefense',title:'相手の守備別',values:['高い位置から守備','中央を固める守備','サイドへ誘導する守備','最終ラインが低い','1人が対応','複数人で囲む','その他']},
  {id:'pressure',title:'プレスの強さ・方向別',values:['強いプレスなし','前からプレス','横から寄せ','後ろから追われる','複数人に囲まれる']},
  {id:'zone',title:'ピッチ上の場所別',values:['自陣','中盤','敵陣','ペナルティエリア付近']},
  {id:'scoreState',title:'試合状況別',values:['リード','同点','ビハインド']}
 ];
 const actionKeys=['scan','orientation','position','support','movement'];
 const actionLabels={scan:'周囲確認',orientation:'身体の向き',position:'立ち位置',support:'サポート角度',movement:'動き出し'};
 const choiceKeys=['パス','ドリブル','シュート','キープ','その他'];
 const valid=v=>v&&v!=='映像で確認できない'&&!String(v).includes('不明');
 const grouped=dimensions.map(dim=>{
  const groups=dim.values.map(value=>{
   const subset=scenes.filter(x=>x.fields[dim.id]===value);
   const counts={};
   subset.forEach(x=>{const f=x.fields;if(valid(f.decision))counts[f.decision]=(counts[f.decision]||0)+1;});
   const outcomes={};
   subset.forEach(x=>{const f=x.fields;if(valid(f.outcome))outcomes[f.outcome]=(outcomes[f.outcome]||0)+1;});
   const actions=actionKeys.map(key=>{
    const rows=subset.filter(x=>valid(x.fields[key]));
    const tally={};rows.forEach(x=>{const v=x.fields[key];tally[v]=(tally[v]||0)+1;});
    const top=Object.entries(tally).sort((a,b)=>b[1]-a[1])[0];
    return {key,label:actionLabels[key],count:rows.length,top:top?.[0]||'',topCount:top?.[1]||0};
   }).filter(x=>x.count);
   return {value,subset,counts,outcomes,actions};
  }).filter(g=>g.subset.length);
  return {dim,groups};
 });
 const opponentGroups={};
 scenes.forEach(x=>{const key=x.opponent||'相手チーム未入力';(opponentGroups[key]||(opponentGroups[key]=[])).push(x);});
 const opponentHtml=Object.entries(opponentGroups).sort((a,b)=>b[1].length-a[1].length).map(([name,rows])=>'<div class="listitem"><div class="grow"><b>'+escT(name)+'</b><div class="tiny muted">'+rows.length+'場面｜'+(rows.length>=3?'状況別の傾向を比較できます':'評価保留：3場面以上必要')+'</div></div></div>').join('');
 const html=grouped.map(({dim,groups})=>{
  const cards=groups.map(g=>{
   const n=g.subset.length,ready=n>=3;
   const decisions=choiceKeys.filter(k=>g.counts[k]).map(k=>k+' '+g.counts[k]+'件').join('／');
   const results=Object.entries(g.outcomes).sort((a,b)=>b[1]-a[1]).map(([k,v])=>k+' '+v+'件').join('／');
   const actionSummary=ready?g.actions.map(a=>'<div class="tiny">'+escT(a.label)+'：最多「'+escT(a.top)+'」'+a.topCount+'/'+a.count+'件</div>').join(''):'<div class="tiny muted">行動傾向は評価保留（3場面以上必要）</div>';
   return '<div class="card" style="margin-top:8px"><b>'+escT(g.value)+'</b><div class="tiny muted">'+n+'場面'+(ready?'':'｜評価保留')+'</div>'+actionSummary+'<div class="tiny" style="margin-top:6px">プレー選択：'+escT(decisions||'記録なし')+'</div><div class="tiny">プレー結果：'+escT(results||'記録なし')+'</div></div>';
  }).join('');
  return '<div style="margin-top:12px"><h3>'+escT(dim.title)+'</h3>'+(cards||'<div class="tiny muted">該当する手動確認済み場面がありません。</div>')+'</div>';
 }).join('');
 const content=scenes.length?'<div><h3>相手チーム別の記録</h3>'+opponentHtml+'</div>'+html:'<div class="empty">手動確認済みの場面がありません。試合分析で相手チーム・守備・プレス・場所・試合状況を入力して保存してください。</div>';
 host.innerHTML='<h2>⑨ 相手チーム・試合状況別の判断分析</h2><p class="tiny muted">陸玖本人として確認し、手動保存した場面だけを集計。相手の守備、プレス、プレー位置、リード・同点・ビハインド別に、行動・選択・結果の記録を整理します。</p>'+content+'<div class="tiny muted" style="margin-top:10px">各状況で3場面未満の場合は判断傾向を評価保留にします。プレー選択や結果だけで正解・不正解を決めません。相手チーム名が未入力の記録は「相手チーム未入力」にまとめます。</div>';
 const report=document.getElementById('tacticalMatchReports');
 const graph=document.getElementById('tacticalGrowthGraph');
 if(report)report.insertAdjacentElement('afterend',host);else if(graph)graph.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
}

function getTacticalDecisionScenarios(){
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 const scenes=[];
 matches.forEach(match=>(match.candidateEvents||[]).forEach(ev=>{
  const review=ev.tacticalReview;
  if(ev.reviewLabel!=='陸玖'||!review?.reviewedAt||!review.fields)return;
  scenes.push({fields:review.fields,match,ev});
 }));
 const scenarios=[];
 const add=(key,value,title,setup,task,criteria,minutes,source)=>{
  const rows=scenes.filter(x=>x.fields[key]===value);
  if(rows.length>=3){
   const flags=[];
   rows.forEach(x=>{
    const f=x.fields;
    if(f.scan==='確認したが首振りなし')flags.push('受ける前の確認');
    if(f.orientation==='後ろ向き')flags.push('半身で受ける準備');
    if(f.position==='味方と位置が重なる')flags.push('立ち位置の重なり');
    if(f.support==='真後ろ'||f.support==='パスコースを作れていない')flags.push('サポート角度');
    if(f.movement==='動き出しなし'||f.movement==='足元に受けに来た')flags.push('スペースへの動き出し');
   });
   const repeated=Object.entries(flags.reduce((a,v)=>(a[v]=(a[v]||0)+1,a),{})).sort((a,b)=>b[1]-a[1])[0];
   scenarios.push({title,setup,task,criteria,minutes,personalized:true,count:rows.length,context:value,contextKey:key,focus:repeated?.[0]||'',focusCount:repeated?.[1]||0,source});
  }
 };
 add('pressure','前からプレス','前からのプレスを受ける','親が正面からゆっくり寄せる。陸玖は味方役からパスを受ける。','受ける前に周囲を確認し、半身で受ける。前が閉じていたら横・後ろへつなぎ、空けばターンして前進。','顔を上げて選択肢を2つ確認し、無理な突進をせず次のプレーにつなぐ',8,'手動確認済みの「前からプレス」');
 add('pressure','複数人に囲まれる','複数方向から囲まれた時','親ともう1人が左右から距離を保って寄せる。安全なスペースを確保する。','ボールを受ける前に左右を見て、ファーストタッチで片側へ逃げる。難しければワンタッチで味方役へ戻す。','相手に突っ込まず、逃げ道か味方へのパスを選べる',8,'手動確認済みの「複数人に囲まれる」');
 add('zone','ペナルティエリア付近','ゴール前のパスかシュートか','ゴール前にコーンでゴールと守備役を作る。味方役は斜め前に立つ。','守備役の位置を見て、シュート・味方へのパス・運んで角度を作る、の3択を声に出してから実行。','ゴールが見え、コースがあればシュート。相手が寄せたら味方を使うなど状況に合う選択を説明できる',10,'手動確認済みの「ペナルティエリア付近」');
 add('scoreState','リード','リード時の落ち着いた判断','親が守備役、味方役を1人置く。時間を意識した短いゲームを行う。','無理に中央突破せず、空いた安全なパスコースやキープを選ぶ。奪われたらすぐ守備に切り替える。','安全な選択肢を探し、味方につなぐ・ボールを守る判断を説明できる',8,'手動確認済みの「リード」');
 add('scoreState','同点','同点時の前進判断','中盤から開始。守備役は中央か片側を閉じる。','前進できるスペース、味方へのパス、ドリブルの3択を見比べ、最も有効な方法を選ぶ。','急ぎすぎず、前進できる時は思い切って仕掛ける',8,'手動確認済みの「同点」');
 add('scoreState','ビハインド','ビハインド時の攻撃判断','残り時間を決めて、攻撃側がゴールを目指すミニゲーム。','前進する選択を優先しつつ、相手が複数で寄せたら味方を使って攻撃を続ける。','焦って無理な突破を繰り返さず、味方と連携してチャンスを作る',8,'手動確認済みの「ビハインド」');
 return {scenes,personalized:scenarios, general:[
  {title:'一般練習：前からのプレスを外す',setup:'親が正面からゆっくり寄せる。',task:'受ける前に左右を見て、半身で受ける。空いた側へ運ぶか味方役へパス。',criteria:'顔を上げて選択肢を2つ確認する',minutes:8},
  {title:'一般練習：ゴール前の3択',setup:'コーンでゴールと守備役を作り、斜め前に味方役を置く。',task:'シュート・パス・ドリブルの3択を見てからプレーする。',criteria:'選んだ理由を一言で説明できる',minutes:10},
  {title:'一般練習：試合状況を変えるミニゲーム',setup:'リード・同点・ビハインドの設定を各2分で切り替える。',task:'リードはボールを守る、同点は状況を見て前進、ビハインドは味方と連携してゴールを狙う。',criteria:'状況に応じてプレーの優先順位を変えられる',minutes:8}
 ]};
}
function renderTacticalDecisionScenarios(){
 const videoView=document.getElementById('video');if(!videoView)return;
 let host=document.getElementById('tacticalDecisionScenarios');
 if(!host){host=document.createElement('section');host.id='tacticalDecisionScenarios';host.className='card';}
 const data=getTacticalDecisionScenarios();
 const personalized=data.personalized;
 const cards=(personalized.length?personalized:data.general).map((x,i)=>
  '<div class="card" style="margin-top:9px"><b>'+escT(x.title)+'</b><div class="tiny muted">'+(x.personalized?'陸玖の手動確認済み記録から作成｜'+x.count+'場面':'一般的な判断練習｜陸玖本人の弱点を示すものではありません')+'</div>'+
  (x.focus?'<div class="tiny">繰り返し確認された練習テーマ候補：'+escT(x.focus)+'（該当記録 '+x.focusCount+'件）</div>':'')+
  '<div class="tiny" style="margin-top:6px"><b>準備：</b>'+escT(x.setup)+'</div><div class="tiny"><b>やること：</b>'+escT(x.task)+'</div><div class="tiny"><b>できた目安：</b>'+escT(x.criteria)+'</div><div class="tiny muted">目安 '+x.minutes+'分｜'+(x.personalized?escT(x.source):'安全な強度で行い、成功・失敗を責めず判断理由を確認')+'</div></div>'
 ).join('');
 const planNote=personalized.length?'<div class="note success">本人確認済みの記録から作成した練習テーマを、次週の練習計画にも反映します。</div>':'<div class="note">状況別の本人確認済み記録が各3場面に満たないため、一般練習を表示しています。記録が増えるまで陸玖本人の改善点とは判断しません。</div>';
 host.innerHTML='<h2>⑩ 試合状況を再現する判断トレーニング</h2><p class="tiny muted">相手のプレス、ゴール前、リード・同点・ビハインドの場面を短い練習に置き換えます。手動確認済みの状況が十分な場合だけ個別シナリオを作ります。</p>'+planNote+cards+'<div class="tiny muted" style="margin-top:10px">小学生向けに短時間・低〜中強度で実施。接触や強い競り合いは避け、親子で安全な距離を保って行ってください。各シナリオの評価は正解率ではなく、選択肢を見て理由を説明できたかで確認します。</div>';
 const situation=document.getElementById('tacticalSituationAnalysis');
 if(situation)situation.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
}
function applyTacticalDecisionTrainingPlan(plans){
 if(!Array.isArray(plans)||!plans.length)return plans;
 const data=getTacticalDecisionScenarios();
 const chosen=data.personalized[0];
 const base=plans[2]||plans[0];
 if(chosen&&base){
  const note='【試合状況を再現する判断練習】'+chosen.title+'。'+chosen.task+' 成功の目安：'+chosen.criteria+'。本人確認済み '+chosen.count+'場面の状況を反映。';
  plans[2] = {...base, title:'試合状況別の判断トレーニング', category:'判断力', minutes:chosen.minutes, note:(base.note?base.note+'\\n\\n':'')+note, why:'手動確認済みの同じ試合状況 '+chosen.count+'場面から練習シナリオを作成'};
 }
 return plans;
}


function getTacticalTrainingRecords(){
 const rows=(typeof state!=='undefined'&&Array.isArray(state.tacticalDecisionTrainingRecords))?state.tacticalDecisionTrainingRecords:[];
 return rows.filter(x=>x&&x.player==='陸玖'&&x.completed===true&&x.responseSpeed&&x.optionsFound&&x.adapted);
}
function summarizeTacticalTraining(){
 const rows=getTacticalTrainingRecords().slice().sort((a,b)=>String(a.date).localeCompare(String(b.date)));
 const recent=rows.slice(-5);
 if(recent.length<3)return {rows,recent,ready:false,reason:'本人の実施記録が3回未満です。3回以上記録すると傾向を表示します。'};
 const fast=recent.filter(x=>x.responseSpeed==='2秒以内').length;
 const slow=recent.filter(x=>x.responseSpeed==='3秒以上').length;
 const options=recent.filter(x=>x.optionsFound==='3つ以上').length;
 const limited=recent.filter(x=>x.optionsFound==='1つ').length;
 const adapted=recent.filter(x=>x.adapted==='状況に合わせて変えられた').length;
 const unchanged=recent.filter(x=>x.adapted==='状況が変わっても同じ選択だった').length;
 const scores=[{key:'speed',label:'判断の速さ',score:fast-slow,detail:fast+'回は2秒以内／'+slow+'回は3秒以上'},{key:'options',label:'選択肢の見つけ方',score:options-limited,detail:options+'回は3つ以上／'+limited+'回は1つ'},{key:'adapt',label:'状況に応じた判断の変化',score:adapted-unchanged,detail:adapted+'回は状況に合わせて変更／'+unchanged+'回は同じ選択'}];
 const priority=scores.slice().sort((a,b)=>a.score-b.score)[0];
 return {rows,recent,ready:true,scores,priority};
}
function renderTacticalTrainingLog(){
 const videoView=document.getElementById('video');if(!videoView)return;
 let host=document.getElementById('tacticalTrainingLog');
 if(!host){host=document.createElement('section');host.id='tacticalTrainingLog';host.className='card';}
 const scenarios=getTacticalDecisionScenarios();
 const available=[...scenarios.personalized,...scenarios.general];
 const summary=summarizeTacticalTraining();
 const options=available.map((x,i)=>'<option value="'+i+'">'+escT(x.title)+(x.personalized?'（本人記録に基づく）':'（一般練習）')+'</option>').join('');
 const metrics=summary.ready?summary.scores.map(x=>'<div class="listitem"><div class="grow"><b>'+escT(x.label)+'</b><div class="tiny muted">'+escT(x.detail)+'</div></div><span class="tiny">'+(x.score>0?'良い傾向':x.score<0?'練習テーマ候補':'記録上は同程度')+'</span></div>').join(''):'<div class="note">評価保留：'+escT(summary.reason)+' 記録のない練習を実施済みとして扱いません。</div>';
 const priority=summary.ready?'<div class="note"><b>次回の重点：</b>'+escT(summary.priority.label)+'。'+(summary.priority.key==='speed'?'まずは落ち着いて周囲を見てから、短い時間で選択肢を決める練習。':summary.priority.key==='options'?'受ける前に左右・前方を見て、パス・ドリブル・キープなど複数の選択肢を探す練習。':'守備役の位置や試合状況を変え、状況に応じて選択を切り替える練習。')+'</div>':'';
 host.innerHTML='<h2>⑪ 判断トレーニング実施記録・自動調整</h2><p class="tiny muted">練習後に陸玖本人が実際に行った結果だけを記録します。動画や試合分析から実施結果を推測しません。</p><div class="card"><b>今回の練習</b><label class="label">シナリオ<select id="tacticalTrainingScenario">'+options+'</select></label><label class="label">判断を決めるまでの時間<select id="tacticalTrainingSpeed"><option value="2秒以内">2秒以内</option><option value="2〜3秒">2〜3秒</option><option value="3秒以上">3秒以上</option><option value="判断できなかった">判断できなかった</option></select></label><label class="label">見つけられた選択肢<select id="tacticalTrainingOptions"><option value="1つ">1つ</option><option value="2つ">2つ</option><option value="3つ以上">3つ以上</option><option value="数えられなかった">数えられなかった</option></select></label><label class="label">状況が変わった時の判断<select id="tacticalTrainingAdapt"><option value="状況に合わせて変えられた">状況に合わせて変えられた</option><option value="同じ選択を続けた">同じ選択を続けた</option><option value="状況が変わっても同じ選択だった">状況が変わっても同じ選択だった</option><option value="状況変化なし">状況変化なし</option><option value="判断できなかった">判断できなかった</option></select></label><label class="label">ひとことメモ（任意）<input id="tacticalTrainingNote" maxlength="180" placeholder="例：右を閉じられたので左へパス"></label><button id="tacticalTrainingSave">この練習結果を記録</button><div class="tiny muted">記録者が実施を確認して保存してください。タイム計測が難しい場合は体感で選択できます。本人の記録だけを集計します。</div></div><div class="card"><h3>実施結果から見た傾向</h3><div class="tiny muted">集計対象：直近5回まで／評価開始：3回以上</div>'+metrics+priority+'<div class="tiny muted">これは練習記録の振り返りであり、医学的・競技能力の確定評価ではありません。</div></div><div class="card"><h3>最近の実施記録</h3>'+(summary.rows.length?summary.rows.slice(-8).reverse().map(x=>'<div class="listitem"><div class="grow"><b>'+escT(x.date)+'｜'+escT(x.scenarioTitle)+'</b><div class="tiny muted">速さ：'+escT(x.responseSpeed)+'｜選択肢：'+escT(x.optionsFound)+'｜状況対応：'+escT(x.adapted)+'</div></div></div>').join(''):'<div class="tiny muted">まだ実施記録はありません。</div>')+'</div>';
 document.getElementById('tacticalTrainingSave').onclick=()=>{
  const scenarioIndex=Number(document.getElementById('tacticalTrainingScenario').value)||0;
  const scenario=available[scenarioIndex]||available[0];
  if(!scenario){alert('記録する練習シナリオがありません。');return;}
  const responseSpeed=document.getElementById('tacticalTrainingSpeed').value;
  const optionsFound=document.getElementById('tacticalTrainingOptions').value;
  const adapted=document.getElementById('tacticalTrainingAdapt').value;
  if(!responseSpeed||!optionsFound||!adapted){alert('3項目を選択してください。');return;}
  if(!Array.isArray(state.tacticalDecisionTrainingRecords))state.tacticalDecisionTrainingRecords=[];
  state.tacticalDecisionTrainingRecords.push({id:'tdt-'+Date.now()+'-'+Math.random().toString(36).slice(2,7),player:'陸玖',completed:true,date:typeof today==='function'?today():new Date().toISOString().slice(0,10),scenarioTitle:scenario.title,scenarioPersonalized:!!scenario.personalized,responseSpeed,optionsFound,adapted,note:(document.getElementById('tacticalTrainingNote').value||'').trim().slice(0,180)});
  if(typeof persist==='function')persist();
  renderTacticalTrainingLog();
  alert('陸玖の判断トレーニング実施結果を保存しました。');
 };
 const scenariosPanel=document.getElementById('tacticalDecisionScenarios');
 if(scenariosPanel)scenariosPanel.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
}
function applyTacticalTrainingResultPlan(plans){
 if(!Array.isArray(plans)||!plans.length)return plans;
 const summary=summarizeTacticalTraining();
 if(!summary.ready)return plans;
 const base=plans[2]||plans[0];if(!base)return plans;
 const p=summary.priority;
 const details={
  speed:{title:'判断を素早く決めるトレーニング',note:'周囲を確認し、パス・ドリブル・キープの選択肢を見つけてから判断する。無理に急がせず、落ち着いた判断を目指す。'},
  options:{title:'選択肢を複数見つけるトレーニング',note:'受ける前に左右・前方を確認し、パス・ドリブル・キープのうち2つ以上の選択肢を声に出してから実行する。'},
  adapt:{title:'状況変化に合わせる判断トレーニング',note:'守備役の位置や試合状況を途中で変え、最初の選択にこだわらず、空いたスペースや味方に合わせて判断を変える。'}
 };
 const d=details[p.key];
 plans[2]={...base,title:d.title,category:'判断力',minutes:10,note:d.note+'\\n\\n【本人の実施記録】直近'+summary.recent.length+'回から次回の重点を調整。',why:'陸玖本人の実施記録 '+summary.recent.length+'回を集計：'+p.label+'（'+p.detail+'）'};
 return applyTacticalTrainingResultPlan(plans);
}


function renderTacticalDecisionGrowthReport(){
 const videoView=document.getElementById('video');if(!videoView)return;
 let host=document.getElementById('tacticalDecisionGrowthReport');
 if(!host){host=document.createElement('section');host.id='tacticalDecisionGrowthReport';host.className='card';}
 const matches=(typeof state!=='undefined'&&Array.isArray(state.matchAnalyses))?state.matchAnalyses:[];
 const matchRows=[];
 matches.forEach(match=>(match.candidateEvents||[]).forEach(ev=>{
  const review=ev.tacticalReview;
  if(ev.reviewLabel!=='陸玖'||!review?.reviewedAt||!review.fields)return;
  const f=review.fields;
  const date=String(review.reviewedAt||match.date||'').slice(0,10);
  if(!date)return;
  matchRows.push({date,matchTitle:match.title||'試合',time:ev.time,fields:f});
 }));
 matchRows.sort((a,b)=>a.date.localeCompare(b.date)||Number(a.time||0)-Number(b.time||0));
 const trainingRows=getTacticalTrainingRecords().filter(x=>String(x.date||'').length===10&&x.date[4]==='-'&&x.date[7]==='-').slice().sort((a,b)=>a.date.localeCompare(b.date));
 const groupByDate=rows=>{const out={};rows.forEach(x=>(out[x.date]||(out[x.date]=[])).push(x));return Object.keys(out).sort().map(date=>({date,items:out[date]}));};
 const matchDays=groupByDate(matchRows),trainingDays=groupByDate(trainingRows);
 const matchReady=matchRows.length>=3&&matchDays.length>=2;
 const trainingReady=trainingRows.length>=3&&trainingDays.length>=2;
 const choices=['パス','ドリブル','シュート','キープ','その他'];
 const matchTimeline=matchDays.slice(-8).map(day=>{
  const scans=day.items.filter(x=>['左右を確認','前方を確認','複数方向を確認','確認したが首振りなし'].includes(x.fields.scan));
  const scanGood=scans.filter(x=>['左右を確認','前方を確認','複数方向を確認'].includes(x.fields.scan)).length;
  const selected=choices.filter(c=>day.items.some(x=>x.fields.decision===c));
  const contexts=['pressure','zone','scoreState'].map(k=>day.items.map(x=>x.fields[k]).filter(v=>v&&v!=='映像で確認できない'));
  const contextCount=contexts.reduce((n,a)=>n+a.length,0);
  return '<div class="listitem"><div class="grow"><b>'+escT(day.date)+'｜試合・手動確認 '+day.items.length+'場面</b><div class="tiny muted">周囲確認：確認できた '+scanGood+'/'+scans.length+'場面（確認不能は分母に含めず）</div><div class="tiny muted">記録されたプレー選択：'+escT(selected.join('・')||'なし')+'（選択肢の数ではありません）</div><div class="tiny muted">状況情報：プレス・場所・試合状況の入力 '+contextCount+'項目</div></div></div>';
 }).join('');
 const trainingTimeline=trainingDays.slice(-8).map(day=>{
  const fast=day.items.filter(x=>x.responseSpeed==='2秒以内').length;
  const slow=day.items.filter(x=>x.responseSpeed==='3秒以上').length;
  const many=day.items.filter(x=>x.optionsFound==='3つ以上').length;
  const one=day.items.filter(x=>x.optionsFound==='1つ').length;
  const adapted=day.items.filter(x=>x.adapted==='状況に合わせて変えられた').length;
  const unchanged=day.items.filter(x=>x.adapted==='状況が変わっても同じ選択だった'||x.adapted==='同じ選択を続けた').length;
  return '<div class="listitem"><div class="grow"><b>'+escT(day.date)+'｜本人の練習実施 '+day.items.length+'回</b><div class="tiny muted">判断の速さ：2秒以内 '+fast+'回／3秒以上 '+slow+'回</div><div class="tiny muted">選択肢：3つ以上 '+many+'回／1つ '+one+'回</div><div class="tiny muted">状況対応：変えられた '+adapted+'回／同じ選択 '+unchanged+'回</div></div></div>';
 }).join('');
 const matchStatus=matchReady?'手動確認済み '+matchRows.length+'場面・'+matchDays.length+'日分':'評価保留（3場面以上かつ2日以上の記録が必要。現在 '+matchRows.length+'場面・'+matchDays.length+'日分）';
 const trainingStatus=trainingReady?'本人実施 '+trainingRows.length+'回・'+trainingDays.length+'日分':'評価保留（本人実施3回以上かつ2日以上の記録が必要。現在 '+trainingRows.length+'回・'+trainingDays.length+'日分）';
 const comparison='<div class="note"><b>両方の変化の見比べ方</b><div class="tiny">試合側：実際の試合で手動確認できた首振り・プレー選択・状況情報の記録数や内容を時系列で確認します。</div><div class="tiny">練習側：本人が実際に行った判断の速さ・見つけた選択肢・状況対応の記録を時系列で確認します。</div><div class="tiny">同じ日付の変化を並べて見られますが、測定方法が違うため共通点数・合算点・因果関係は作りません。試合で選んだプレーの種類を、本人が見つけた選択肢の数として扱いません。</div></div>';
 host.innerHTML='<h2>⑫ 判断力の成長レポート｜試合と練習を時系列で比較</h2><p class="tiny muted">陸玖本人として手動確認した試合場面と、陸玖本人の実施確認がある判断トレーニングを、出どころを分けて日付順に表示します。</p><div class="card"><h3>試合中の判断｜手動確認記録</h3><div class="tiny muted">'+escT(matchStatus)+'</div>'+(matchTimeline||'<div class="tiny muted">対象となる手動確認済み試合記録はありません。</div>')+'<div class="tiny muted">判断の速さ（秒数）と本人が見つけた選択肢の数は、手動確認項目にないため試合側では評価しません。</div></div><div class="card"><h3>判断トレーニング｜本人の実施記録</h3><div class="tiny muted">'+escT(trainingStatus)+'</div>'+(trainingTimeline||'<div class="tiny muted">本人の実施記録はありません。</div>')+'<div class="tiny muted">未実施・未入力・判断できなかった記録を、成功として数えません。</div></div>'+comparison+'<div class="tiny muted">評価保留は能力が低いという意味ではなく、傾向を判断するための記録数がまだ足りないという意味です。記録のない日を補間したり、映像から練習結果を推測したりしません。</div>';
 const log=document.getElementById('tacticalTrainingLog');
 if(log)log.insertAdjacentElement('afterend',host);else videoView.appendChild(host);
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