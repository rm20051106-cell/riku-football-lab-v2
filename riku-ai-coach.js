(function(){
'use strict';
const ID='rikuDedicatedCoach';
const UNKNOWN='映像で確認できない';
const DOMAINS=[
 {id:'dribble',label:'ドリブル突破',focus:'ドリブル',title:'加速ドリブル＋相手を見た1対1',category:'突破・ドリブル',minutes:12,drill:'マーカーで加速して運び、親子1対1で相手の重心を見て左右を選ぶ。抜いた後の2〜3歩まで加速。'},
 {id:'shooting',label:'シュート・フリーキック',focus:'シュート',title:'助走・軸足・ミートの確認',category:'シュート',minutes:12,drill:'近距離から助走のリズムと軸足の位置を確認。狙う場所を決め、力を抑えて左右・コースを変えて蹴る。'},
 {id:'firstTouch',label:'ファーストタッチ',focus:'ボールを受ける',title:'首振り→半身→前向きタッチ',category:'受ける動き',minutes:10,drill:'パスが出る前に左右を確認。半身で受け、相手から遠い側または前方へタッチする。'},
 {id:'transition',label:'攻守の切り替え',focus:'守備・プレス',title:'切り替え直後の最初の3歩',category:'アジリティ',minutes:10,drill:'ボールを失った合図で最初の3歩を出し、相手の前進コースを限定。奪った想定では前方を見て出口を選ぶ。'},
 {id:'physical',label:'フィジカル',focus:'その他',title:'加速・減速・着地の基礎',category:'アジリティ',minutes:8,drill:'短い加速を3〜4本、左右の減速・切り返しを各3回。ジャンプは軽く行い、静かな着地を確認する。'},
 {id:'decision',label:'試合中の判断・ポジショニング',focus:'オフザボール',title:'受ける前の確認とサポート角度',category:'受ける動き',minutes:10,drill:'受ける前に左右を確認し、保持者の斜め前・横へ立ってパスコースを作る。空いたスペースへ動き出す。'}
];
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function data(){if(typeof state==='undefined')return null;state.rikuCoachReviews=Array.isArray(state.rikuCoachReviews)?state.rikuCoachReviews:[];return state;}
function dateNow(){return typeof today==='function'?today():new Date().toISOString().slice(0,10);}
function valid(v){return v!=null&&String(v).trim()!==''&&String(v)!==UNKNOWN&&!String(v).includes('不明')&&!String(v).includes('未確認')&&!String(v).includes('判定できない');}
function verifiedScenes(s){const out=[];(s.matchAnalyses||[]).forEach(m=>(m.candidateEvents||[]).forEach(e=>{if(e.reviewLabel==='陸玖'&&e.tacticalReview&&e.tacticalReview.reviewedAt&&e.tacticalReview.fields)out.push({match:m,event:e,fields:e.tacticalReview.fields,dribble:e.tacticalReview.dribbleBreakthrough?.fields||null});}));return out;}
function setupKey(x){const q=x.setup||x;return JSON.stringify(q,Object.keys(q||{}).sort());}
function sameSetupRows(rows,latest){if(!latest||!latest.setup)return [];const k=setupKey(latest);return rows.filter(x=>x.setup&&setupKey(x)===k);}
function makeEvidence(s){
 const scenes=verifiedScenes(s),out={};
 const dribbleGroups={};
 scenes.forEach(x=>{if(!x.dribble||!valid(x.dribble.attempt)||x.dribble.attempt==='1対1の突破場面ではない')return;const c=x.event.tacticalReview?.context||{};const key=[c.zone,c.pressure,c.defense,c.space,c.scoreState].join('|');if([c.zone,c.pressure,c.defense,c.space,c.scoreState].some(valid))dribbleGroups[key]=(dribbleGroups[key]||0)+1;});
 function bucket(id){return out[id]||(out[id]={count:0,issues:{},strengths:{},sources:[],latest:''});}
 function add(id,value,source,date,kind){
  if(!valid(value))return;const b=bucket(id);b.count++;b.latest=date>b.latest?date:b.latest;
  const v=String(value);
  if(kind==='bad'){b.issues[v]=(b.issues[v]||0)+1;}else if(kind==='good'){b.strengths[v]=(b.strengths[v]||0)+1;}
  if(b.sources.length<5)b.sources.push(source);
 }
 const classify=(v)=>{const x=String(v);if(/確認したが首振りなし|ボールだけを見ていた|後ろ向き|味方と位置が重なる|真後ろ|パスコースを作れていない|動き出しなし|足元に受けに来た|ボールを失った|相手に奪われた|足元に止まりすぎ|相手に近い側|後方|立ち止まった|反応が遅れた|プレスに行かなかった|役割が重なった|ボールだけを追いかけた|振りが小さい|振りが大きく不安定|途中で止まる|振り抜き方向がずれる|上体が反り気味|前に倒れすぎ|左右に傾く|開きすぎ|前に崩れる|横に流れる|後ろに残る|着地が不安定/.test(x))return 'bad';if(/左右を確認|前方を確認|複数方向を確認|半身|スペースへ動いた|相手と相手の間|相手の背後|外側のスペース|前方斜め|後方斜め|スムーズに振れている|安定して立てる|ゴール|前進できた|味方につながった|シュートにつながった|チャンスを作れた|前方へ置けた|相手から遠い側/.test(x))return 'good';return 'known';};
 scenes.forEach(x=>{
  const f=x.fields||{},d=x.dribble||{};
  ['scan','orientation','position','support','movement','decision','outcome'].forEach(k=>{const v=f[k];const c=classify(v);add('decision',v,'試合 '+(x.match.date||'日付不明')+'｜'+k,x.match.date||'',c);});
  const context=x.event.tacticalReview?.context||{},contextKey=[context.zone,context.pressure,context.defense,context.space,context.scoreState].join('|');
  if(d.attempt&&d.attempt!=='1対1の突破場面ではない'&&dribbleGroups[contextKey]>=3)Object.keys(d).forEach(k=>{const v=d[k];const c=classify(v);add('dribble',v,'同条件の突破場面 '+(x.match.date||'日付不明')+'｜'+k,x.match.date||'',c);});
 });
 const shotAll=(s.shootingSpecialistRecords||[]).slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
 const shot=shotAll.length?sameSetupRows(shotAll,shotAll[0]):[];
 shot.forEach(r=>{const b=bucket('shooting');b.count++;b.latest=r.date>b.latest?r.date:b.latest;const f=r.fields||{};Object.entries(f).forEach(([k,v])=>{const c=classify(v);if(c==='bad')b.issues[v]=(b.issues[v]||0)+1;if(c==='good')b.strengths[v]=(b.strengths[v]||0)+1;});if(b.sources.length<5)b.sources.push('同条件フォーム '+(r.date||'日付不明')+'｜'+(r.kind||'キック'));});
 const ftAll=(s.firstTouchRecords||[]).slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
 const ft=ftAll.length?sameSetupRows(ftAll,ftAll[0]):[];
 ft.forEach(r=>{const b=bucket('firstTouch');b.count++;b.latest=r.date>b.latest?r.date:b.latest;Object.entries(r.fields||{}).forEach(([k,v])=>{const c=classify(v);if(c==='bad')b.issues[v]=(b.issues[v]||0)+1;if(c==='good')b.strengths[v]=(b.strengths[v]||0)+1;});if(b.sources.length<5)b.sources.push('同条件ファーストタッチ '+(r.date||'日付不明'));});
 const trAll=(s.transitionAnalysisRecords||[]).slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
 const tr=trAll.length?sameSetupRows(trAll,trAll[0]):[];
 tr.forEach(r=>{const b=bucket('transition');b.count++;b.latest=r.date>b.latest?r.date:b.latest;Object.entries(r.fields||{}).forEach(([k,v])=>{const c=classify(v);if(c==='bad')b.issues[v]=(b.issues[v]||0)+1;if(c==='good')b.strengths[v]=(b.strengths[v]||0)+1;});if(b.sources.length<5)b.sources.push('同条件切り替え '+(r.date||'日付不明'));});
 const measures=(s.measures||[]).filter(x=>['30m走','アジリティ','立ち幅跳び','100m走'].includes(x.type)&&Number.isFinite(Number(x.value)));
 const m=bucket('physical');m.count=measures.length;m.latest=measures.map(x=>x.date||'').sort().slice(-1)[0]||'';
 ['30m走','アジリティ','立ち幅跳び','100m走'].forEach(type=>{const rows=measures.filter(x=>x.type===type).sort((a,b)=>String(b.date).localeCompare(String(a.date)));if(rows.length>=2){const a=rows[0],b=rows[1],same=a.unit===b.unit&&JSON.stringify(a.physicalConditions||null)===JSON.stringify(b.physicalConditions||null);if(same){const d=Number(a.value)-Number(b.value),better=type==='立ち幅跳び'?d>0:d<0;if(d!==0)(better?m.strengths:m.issues)[type+'：'+(better?'改善方向の変化':'前回と異なる値')]=1;}}});
 return {domains:out,scenes,training:(s.trainings||[]).slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))),measures};
}
function strongest(map){return Object.entries(map||{}).sort((a,b)=>b[1]-a[1])[0]||null;}
function planFor(s){
 const ev=makeEvidence(s),review=s.rikuCoachReviews[0]||null,rank=[];
 DOMAINS.forEach(d=>{
  const b=ev.domains[d.id]||{count:0,issues:{},strengths:{},sources:[]};
  const issue=strongest(b.issues),strength=strongest(b.strengths);
  let ready=false,score=0,why='';
  if(d.id==='dribble'){ready=b.count>=3&&issue&&issue[1]>=2;score=ready?issue[1]+1:0;why=ready?'手動確認済みの突破場面で同じ改善項目が複数回確認された':'';}
  else if(['shooting','firstTouch','transition'].includes(d.id)){ready=b.count>=3&&issue&&issue[1]>=2;score=ready?issue[1]:0;why=ready?'専門分析の記録3件以上で同じ観察項目が複数回確認された':'';}
  else if(d.id==='decision'){ready=ev.scenes.length>=3&&issue&&issue[1]>=2;score=ready?issue[1]:0;why=ready?'本人確認済み試合場面で同じ観察項目が繰り返し記録された':'';}
  else if(d.id==='physical'){ready=Object.keys(b.issues).length>0;score=ready?1:0;why=ready?'同じ種目・単位・計測条件の2回以上の記録に変化がある':'';}
  if(review&&review.focus===d.focus){score+=review.result==='難しかった'?2:review.result==='一部できた'?1:review.result==='できた'?0:-1; if(review.result)why+=(why?'／':'')+'直近の本人振り返り「'+review.result+'」を反映';}
  rank.push({...d,count:b.count,issue,strength,ready,score,why:why||'十分な反復記録がないため評価保留',sources:b.sources,issues:b.issues,strengths:b.strengths});
 });
 rank.sort((a,b)=>b.score-a.score||b.count-a.count);
 const selected=rank.filter(x=>x.ready&&x.score>0).slice(0,3);
 const training=ev.training,now=Date.parse(dateNow()+'T00:00:00');
 const recent=training.filter(t=>{const dt=Date.parse(String(t.date||'')+'T00:00:00');return Number.isFinite(dt)&&now-dt<=30*86400000;});
 const weekly=selected.length?selected:[rank.find(x=>x.id==='dribble'),rank.find(x=>x.id==='firstTouch')].filter(Boolean);
 const sessions=weekly.slice(0,3).map((x,i)=>({...x,day:['月曜','火曜','水曜'][i],minutes:x.minutes+(review&&review.focus===x.focus&&review.result==='難しかった'?2:0)}));
 return {rank,selected,sessions,trainingCount:training.length,recentCount:recent.length,scenes:ev.scenes.length,ev,review};
}
function render(){
 const s=data(),anchor=document.getElementById('dailyPlan');if(!s||!anchor)return;
 let panel=document.getElementById(ID);if(!panel){panel=document.createElement('div');panel.id=ID;panel.className='card';anchor.closest('.card')?.insertAdjacentElement('afterend',panel);}
 const p=planFor(s),top=p.rank.filter(x=>x.score>0||x.ready).slice(0,4);
 const strength=p.rank.filter(x=>x.strength&&x.strength[1]>=2).slice(0,3);
 const focusHtml=top.length?top.map((x,i)=>'<div class="listitem"><div class="grow"><b>'+(i+1)+'. '+esc(x.label)+'｜'+esc(x.title)+'</b><div class="tiny muted">'+esc(x.why)+'｜観察・分析記録 '+x.count+'件'+(x.issue?'｜繰り返し確認 '+x.issue[1]+'件':'')+'</div></div></div>').join(''):'<div class="note">課題の優先順位は評価保留です。各分析を手動で保存し、同じ項目が繰り返し確認できるまで断定しません。</div>';
 const strengthsHtml=strength.length?strength.map(x=>'<div class="tiny">・'+esc(x.label)+'：'+esc(x.strength[0])+'（'+x.strength[1]+'件の記録）</div>').join(''):'<div class="tiny muted">繰り返し確認された強みはまだ特定できません。未確認項目を強みとして扱いません。</div>';
 const sessions=p.sessions.map((x,i)=>'<div class="listitem"><div class="grow"><b>'+x.day+'｜'+esc(x.title)+'</b><div class="tiny muted">'+x.minutes+'分｜'+esc(x.why)+'</div><div class="tiny">'+esc(x.drill)+'</div><button type="button" class="secondary small" data-rac-start="'+i+'">このメニューで練習を始める</button></div></div>').join('');
 const trainingHtml=p.trainingCount?'<div class="tiny">練習記録 '+p.trainingCount+'件／直近30日 '+p.recentCount+'件。練習の実施記録と試合の評価は別々に集計しています。</div>':'<div class="tiny muted">練習履歴はまだありません。練習画面で実施した内容を保存してください。</div>';
 const reviews=s.rikuCoachReviews.slice(0,5).map(x=>'<div class="tiny">'+esc(x.date)+'｜'+esc(x.focus)+'｜'+esc(x.result)+'｜'+esc(x.note||'')+'</div>').join('')||'<div class="tiny muted">コーチへの振り返りはまだありません。</div>';
 panel.innerHTML='<h2>陸玖専用AIコーチ｜記録統合プラン</h2><p class="tiny muted">ドリブル突破・シュート/FK・ファーストタッチ・攻守の切り替え・フィジカル・本人確認済み試合場面・練習履歴を統合。保存された事実だけで提案し、未確認・未測定は評価しません。これは無料・端末内の記録ルールに基づく自動提案で、外部生成AIや有料APIは使用しません。</p><div class="note"><b>記録の全体像</b><div class="tiny">本人確認済み試合 '+p.scenes+'場面｜練習 '+p.trainingCount+'件（直近30日 '+p.recentCount+'件）｜フィジカル測定 '+p.ev.measures.length+'件</div></div><h3>課題の優先順位</h3>'+focusHtml+'<div class="divider"></div><h3>繰り返し確認された強み</h3>'+strengthsHtml+'<div class="divider"></div><h3>今週の練習メニュー（案）</h3><div class="tiny muted">月〜水の短時間メニュー案です。木〜日はチーム活動を優先する既存方針に合わせ、追加メニューは表示しません。実際の日程に合わせて変更できます。</div>'+(sessions||'<div class="empty">練習メニューを作成できません。</div>')+'<div class="divider"></div><h3>練習履歴</h3>'+trainingHtml+'<div class="divider"></div><h3>練習後の振り返り</h3><label class="label">振り返るテーマ<select id="racFocus">'+DOMAINS.map(x=>'<option value="'+esc(x.focus)+'">'+esc(x.label)+'</option>').join('')+'</select></label><label class="label">今回の結果<select id="racResult"><option value="">選択してください</option><option>できた</option><option>一部できた</option><option>難しかった</option><option>実施しなかった</option></select></label><label class="label">次回へのメモ（任意）<textarea id="racNote" maxlength="300" placeholder="例：右はできた。左は相手を見てから切り返したい。"></textarea></label><button type="button" id="racSave">振り返りを保存して次回計画に反映</button><div class="tiny muted" style="margin-top:8px">保存した結果は次回の優先順位・メニュー時間の調整に反映します。練習をしていない場合は「実施しなかった」を選び、できたことに数えません。</div><div class="divider"></div><h3>最近の振り返り</h3>'+reviews+'<div class="tiny muted">根拠の基準：試合の手動確認は3場面以上、各専門分析は3記録以上、同じ改善内容の反復が確認できた場合に課題候補とします。フィジカルは同じ種目・単位・条件で比較できる記録だけを使います。条件がそろわない数値や「映像で確認できない」は推測に使いません。</div>';
 panel.querySelectorAll('[data-rac-start]').forEach(btn=>btn.addEventListener('click',()=>{const x=planFor(s).sessions[Number(btn.dataset.racStart)];if(!x)return;s.menus=Array.isArray(s.menus)?s.menus:[];if(!s.menus.some(m=>m.name===x.title))s.menus.unshift({name:x.title,category:x.category,minutes:x.minutes});if(typeof persist==='function')persist();const menu=document.getElementById('trainMenu');if(menu)menu.value=x.title;const minutes=document.getElementById('trainMinutes');if(minutes)minutes.value=x.minutes;const focus=document.getElementById('trainFocus');if(focus)focus.value=x.focus;const note=document.getElementById('trainNote');if(note)note.value=x.drill;if(typeof showView==='function')showView('training');}));
 panel.querySelector('#racSave').addEventListener('click',()=>{const focus=panel.querySelector('#racFocus').value,result=panel.querySelector('#racResult').value;if(!result){alert('今回の結果を選択してください。');return;}s.rikuCoachReviews.unshift({id:Date.now(),date:dateNow(),focus,result,note:panel.querySelector('#racNote').value.trim().slice(0,300)});if(typeof persist==='function')persist();render();alert('振り返りを保存し、次回の計画に反映しました。');});
}
function install(){if(!data())return;render();if(typeof window.renderAll==='function'&&!window.renderAll.__rikuDedicatedCoachWrapped){const original=window.renderAll;const wrapped=function(){const result=original.apply(this,arguments);render();return result;};wrapped.__rikuDedicatedCoachWrapped=true;window.renderAll=wrapped;}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuDedicatedCoach=render;
})();