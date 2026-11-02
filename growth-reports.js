(function(){
'use strict';
const ID='rikuWeeklyMonthlyGrowthReports';
let mode='week',offset=0;
function getState(){if(typeof state==='undefined')return null;return state;}
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function parseDate(v){if(!/^\d{4}-\d{2}-\d{2}$/.test(String(v||'')))return null;const d=new Date(String(v)+'T12:00:00');return Number.isFinite(d.getTime())?d:null;}
function iso(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function addDays(d,n){const x=new Date(d);x.setDate(x.getDate()+n);return x;}
function period(){
 const now=new Date(),base=new Date(now.getFullYear(),now.getMonth(),now.getDate(),12);
 if(mode==='week'){
  const monday=addDays(base,-((base.getDay()+6)%7)+offset*7);
  return {start:monday,end:addDays(monday,7),label:iso(monday)+' 〜 '+iso(addDays(monday,6))};
 }
 const first=new Date(base.getFullYear(),base.getMonth()+offset,1,12),next=new Date(base.getFullYear(),base.getMonth()+offset+1,1,12);
 return {start:first,end:next,label:first.getFullYear()+'年'+(first.getMonth()+1)+'月'};
}
function inPeriod(date,p){const d=parseDate(date);return !!d&&d>=p.start&&d<p.end;}
function rowsIn(list,p){return (Array.isArray(list)?list:[]).filter(x=>inPeriod(x.date,p));}
function dayCount(list){return new Set(list.map(x=>x.date).filter(Boolean)).size;}
function sum(list,key){return list.reduce((n,x)=>n+(Number(x[key])||0),0);}
function fmt(n){return Number(n||0).toLocaleString('ja-JP',{maximumFractionDigits:2});}
function sameConditions(a,b){
 if(!a||!b||!a.physicalConditions||!b.physicalConditions)return false;
 const x=a.physicalConditions,y=b.physicalConditions;
 const keys=o=>Object.keys(o).filter(k=>k!=='note').sort();
 const kx=keys(x),ky=keys(y);
 return kx.length>0&&kx.join('|')===ky.join('|')&&kx.every(k=>String(x[k]??'')===String(y[k]??''))&&String(a.unit||'')===String(b.unit||'');
}
function physicalComparisons(current,previous){
 const all=[...(current||[]),...(previous||[])].filter(x=>x&&x.type&&Number.isFinite(Number(x.value)));
 const types=[...new Set(all.map(x=>x.type))],out=[];
 types.forEach(type=>{
  const cur=all.filter(x=>x.type===type&&current.includes(x)).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
  const prev=all.filter(x=>x.type===type&&previous.includes(x)).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
  if(!cur.length)return;
  const latest=cur[0],match=prev.find(x=>sameConditions(latest,x));
  if(!match){out.push({type,latest,comparison:'同じ計測条件の前期間データがないため比較保留'});return;}
  const diff=Number(latest.value)-Number(match.value);
  let direction='数値差 '+(diff>0?'+':'')+fmt(diff)+' '+(latest.unit||'');
  if(Math.abs(diff)<0.000001)direction='同じ値';
  else if(/30m走|100m走|アジリティ/.test(type))direction=(diff<0?'改善方向':'反対方向')+'の数値変化（'+(diff>0?'+':'')+fmt(diff)+' '+(latest.unit||'')+'）';
  else if(/立ち幅跳び/.test(type))direction=(diff>0?'改善方向':'反対方向')+'の数値変化（'+(diff>0?'+':'')+fmt(diff)+' '+(latest.unit||'')+'）';
  out.push({type,latest,previous:match,comparison:direction});
 });
 return out;
}
function getData(s,p){
 const previous={start:mode==='week'?addDays(p.start,-7):new Date(p.start.getFullYear(),p.start.getMonth()-1,1,12),end:p.start};
 const trainings=rowsIn(s.trainings,p),prevTrainings=rowsIn(s.trainings,previous);
 const matches=rowsIn(s.matchAnalyses,p),prevMatches=rowsIn(s.matchAnalyses,previous);
 const confirmed=matches.flatMap(m=>(m.candidateEvents||[]).filter(e=>e.reviewLabel==='陸玖').map(e=>({...e,date:m.date||e.date||'',matchTitle:m.title||'試合'})));
 const prevConfirmed=prevMatches.flatMap(m=>(m.candidateEvents||[]).filter(e=>e.reviewLabel==='陸玖').map(e=>({...e,date:m.date||e.date||''})));
 const clips=rowsIn(s.clips,p),forms=rowsIn(s.forms,p);
 const shooting=rowsIn(s.shootingSpecialistRecords,p),firstTouch=rowsIn(s.firstTouchRecords,p),transition=rowsIn(s.transitionAnalysisRecords,p);
 const tactical=rowsIn(s.tacticalDecisionTrainingRecords,p),measures=rowsIn(s.measures,p);
 const prevMeasures=rowsIn(s.measures,previous);
 const assessments=confirmed.filter(e=>e.assessment==='良かった'||e.assessment==='改善したい');
 const good=assessments.filter(e=>e.assessment==='良かった'),improve=assessments.filter(e=>e.assessment==='改善したい');
 const issueGroups={};
 improve.forEach(e=>{const k=e.actionType&&e.actionType!=='未選択'?e.actionType:'プレー種別未分類';issueGroups[k]=(issueGroups[k]||0)+1;});
 const recurring=Object.entries(issueGroups).filter(x=>x[1]>=2).sort((a,b)=>b[1]-a[1]);
 const hardReviews=rowsIn(s.rikuCoachReviews,p).filter(x=>x.result==='難しかった');
 const hardGroups={};hardReviews.forEach(x=>hardGroups[x.focus]=(hardGroups[x.focus]||0)+1);
 Object.entries(hardGroups).filter(x=>x[1]>=2).forEach(x=>recurring.push(['振り返り：'+x[0],x[1]]));
 const nextChecks=[];
 recurring.slice(0,3).forEach(x=>nextChecks.push(x[0]+'の場面を次の試合・動画で再確認する'));
 if(!recurring.length&&trainings.length){
  trainings.slice(0,3).forEach(t=>{if(t.matchCheckPrompt&&!nextChecks.includes(t.matchCheckPrompt))nextChecks.push(t.matchCheckPrompt);});
 }
 if(!nextChecks.length){
  if(!confirmed.length)nextChecks.push('試合動画から陸玖本人の場面を手動確認し、良かった点・改善点を記録する');
  if(!shooting.length&&!firstTouch.length&&!transition.length)nextChecks.push('シュート・ファーストタッチ・攻守の切り替えから、次に確認できる映像を1つ保存する');
  if(!measures.length)nextChecks.push('フィジカル測定を行う場合は路面・計測方法・準備運動・試行回数も一緒に記録する');
 }
 const allAnalyses=shooting.length+firstTouch.length+transition.length;
 return {previous,trainings,prevTrainings,matches,prevMatches,confirmed,prevConfirmed,clips,forms,shooting,firstTouch,transition,tactical,measures,prevMeasures,good,improve,recurring,nextChecks,allAnalyses,physical:physicalComparisons(measures,prevMeasures)};
}
function render(){
 const s=getState(),anchor=document.getElementById('dailyPlan');if(!s||!anchor)return;
 let panel=document.getElementById(ID);
 if(!panel){panel=document.createElement('section');panel.id=ID;panel.className='card';panel.innerHTML='<h2>週間・月間 成長レポート</h2><div id="rgrBody"></div>';const host=anchor.closest('.card');if(host)host.insertAdjacentElement('afterend',panel);else anchor.insertAdjacentElement('afterend',panel);}
 const p=period(),d=getData(s,p),body=panel.querySelector('#rgrBody');
 const prevLabel=mode==='week'?'前週':'前月';
 const trainingDelta=d.trainings.length-d.prevTrainings.length;
 const matchDelta=d.confirmed.length-d.prevConfirmed.length;
 const trainingText=d.trainings.length+'回／'+dayCount(d.trainings)+'日・'+sum(d.trainings,'minutes')+'分';
 const trainingCompare='前期間 '+d.prevTrainings.length+'回（差 '+(trainingDelta>0?'+':'')+trainingDelta+'回）';
 const assessmentText='良かった '+d.good.length+'件／改善したい '+d.improve.length+'件';
 const eventHtml=d.confirmed.length?d.confirmed.slice(0,8).map(e=>'<div class="tiny">・'+esc(e.date)+'｜'+esc(e.matchTitle)+'｜'+esc(e.actionType||'プレー種別未分類')+'｜'+esc(e.assessment||'評価未選択')+(e.note?'｜'+esc(e.note):'')+'</div>').join(''):'<div class="tiny muted">この期間に陸玖本人として手動確認された試合場面はありません。</div>';
 const physHtml=d.physical.length?d.physical.map(x=>'<div class="listitem"><div class="grow"><b>'+esc(x.type)+'｜'+esc(x.latest.value)+' '+esc(x.latest.unit||'')+'</b><div class="tiny muted">測定日 '+esc(x.latest.date)+'｜'+esc(x.comparison)+'</div>'+(x.previous?'<div class="tiny muted">比較元 '+esc(x.previous.date)+'：'+esc(x.previous.value)+' '+esc(x.previous.unit||'')+'</div>':'')+'</div></div>').join(''):'<div class="tiny muted">この期間のフィジカル測定はありません。</div>';
 const recurringHtml=d.recurring.length?d.recurring.slice(0,5).map(x=>'<div class="tiny">・'+esc(x[0])+'：改善したい／難しかった '+x[1]+'件</div>').join(''):'<div class="tiny muted">同じプレー種別で繰り返し確認された課題はありません。記録不足の場合は課題なしと断定しません。</div>';
 const checksHtml=d.nextChecks.length?d.nextChecks.slice(0,4).map(x=>'<div class="tiny">・'+esc(x)+'</div>').join(''):'<div class="tiny muted">次の確認項目は、次回の練習・試合記録が保存されると表示します。</div>';
 const special=d.shooting.length+d.firstTouch.length+d.transition.length;
 body.innerHTML='<div class="btnrow" style="align-items:center;margin-top:4px"><button type="button" class="'+(mode==='week'?'':'secondary')+' small" id="rgrWeek">週間</button><button type="button" class="'+(mode==='month'?'':'secondary')+' small" id="rgrMonth">月間</button><button type="button" class="secondary small" id="rgrPrev">◀ '+prevLabel+'</button><button type="button" class="secondary small" id="rgrNext">次 '+(mode==='week'?'週':'月')+' ▶</button><button type="button" class="secondary small" id="rgrNow">今に戻る</button></div><h3 style="margin-top:12px">'+esc(p.label)+'</h3><div class="tiny muted">集計対象：'+esc(iso(p.start))+' 〜 '+esc(iso(addDays(p.end,-1)))+'。前期間との比較は同じ長さの期間で行います。</div>'+
 '<div class="grid" style="margin-top:12px"><div class="card"><div class="tiny muted">練習記録</div><b>'+trainingText+'</b><div class="tiny muted">'+trainingCompare+'</div></div><div class="card"><div class="tiny muted">本人確認済み試合場面</div><b>'+d.confirmed.length+'場面</b><div class="tiny muted">前期間 '+d.prevConfirmed.length+'場面（差 '+(matchDelta>0?'+':'')+matchDelta+'）</div></div><div class="card"><div class="tiny muted">保存動画・フォーム</div><b>'+d.clips.length+'プレー記録／'+d.forms.length+'フォーム記録</b><div class="tiny muted">AI試合スキャン '+d.matches.length+'件</div></div><div class="card"><div class="tiny muted">専門分析</div><b>'+special+'件</b><div class="tiny muted">シュート '+d.shooting.length+'／ファーストタッチ '+d.firstTouch.length+'／切り替え '+d.transition.length+'</div></div><div class="card"><div class="tiny muted">フィジカル測定</div><b>'+d.measures.length+'件</b><div class="tiny muted">測定種目を混ぜずに集計</div></div><div class="card"><div class="tiny muted">試合の手動評価</div><b>'+assessmentText+'</b><div class="tiny muted">評価未選択は含めません</div></div></div>'+
 '<div class="divider"></div><h3>確認できた成長・良かった記録</h3><div class="note">この期間に「良かった」と手動で記録された場面：'+d.good.length+'件。これは記録された評価件数であり、能力全体の成長率を意味しません。</div>'+eventHtml+
 '<div class="divider"></div><h3>フィジカルの同条件比較</h3>'+physHtml+'<div class="tiny muted">比較は同じ種目・単位・記録された全計測条件が一致する前期間データだけを使用。条件未記録・条件不一致の測定値は比較しません。</div>'+
 '<div class="divider"></div><h3>継続して確認したい課題</h3>'+recurringHtml+
 '<div class="divider"></div><h3>動画・分析の記録内訳</h3><div class="tiny">保存プレー分析 '+d.clips.length+'件／フォーム記録 '+d.forms.length+'件／シュート・FK '+d.shooting.length+'件／ファーストタッチ '+d.firstTouch.length+'件／攻守切り替え '+d.transition.length+'件／判断トレーニング '+d.tactical.length+'件</div><div class="tiny muted">動画ファイルの有無や、AIによる本人特定・プレー自動判定を意味する集計ではありません。保存された記録数のみ表示しています。</div>'+
 '<div class="divider"></div><h3>次回の確認項目</h3>'+checksHtml+
 '<div class="note">記録がない項目は評価しません。練習回数の増減は練習量の記録であり、技術向上の証明ではありません。映像で確認できない内容や未測定の数値は補完していません。</div>';
 panel.querySelector('#rgrWeek').addEventListener('click',()=>{mode='week';offset=0;render();});
 panel.querySelector('#rgrMonth').addEventListener('click',()=>{mode='month';offset=0;render();});
 panel.querySelector('#rgrPrev').addEventListener('click',()=>{offset--;render();});
 panel.querySelector('#rgrNext').addEventListener('click',()=>{if(offset<0){offset++;render();}});
 panel.querySelector('#rgrNow').addEventListener('click',()=>{offset=0;render();});
}
function install(){
 if(!getState())return;render();
 if(typeof window.renderAll==='function'&&!window.renderAll.__rikuGrowthReportWrapped){
  const original=window.renderAll,wrapped=function(){const result=original.apply(this,arguments);render();return result;};
  wrapped.__rikuGrowthReportWrapped=true;window.renderAll=wrapped;
 }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuGrowthReports=render;
})();