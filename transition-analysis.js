(function(){
'use strict';
const ID='rikuTransitionAnalysisPanel',UNKNOWN='映像で確認できない';
const groups=[
{id:'lossReaction',label:'ボールを失った直後の反応',options:[UNKNOWN,'すぐにボールへ向かった','相手の前進コースを切った','近くの味方と挟みに行った','味方のカバーに回った','守備への切り替えが遅れた','反応が確認できない']},
{id:'gainReaction',label:'ボールを奪った直後の反応',options:[UNKNOWN,'前方を確認した','前方へ運び始めた','前進できる味方を探した','安全な味方へつないだ','ボールを保持して落ち着かせた','奪った後の反応が確認できない']},
{id:'firstSteps',label:'切り替え直後の最初の数歩',options:[UNKNOWN,'素早く前へ出た','ボール方向へ加速した','戻る方向へ走った','斜めにコースを切った','立ち止まった・反応が遅れた','動きが画面で確認できない']},
{id:'press',label:'ボールを失った後のプレス',options:[UNKNOWN,'ボール保持者へ寄せた','相手の前進方向を限定した','味方と連動して寄せた','距離を保って遅らせた','プレスに行かなかった','プレス状況が確認できない']},
{id:'cover',label:'味方とのカバー・連携',options:[UNKNOWN,'味方の背後をカバーした','味方と挟み込んだ','空いた中央を埋めた','サイドのスペースを埋めた','味方と役割が重なった','カバーが確認できない']},
{id:'recoveryDirection',label:'守備へ戻る方向',options:[UNKNOWN,'ゴール方向へ戻った','中央を閉じながら戻った','外側から中央へ戻った','ボールとゴールの間に戻った','ボールだけを追いかけた','戻る動きが確認できない']},
{id:'progressDecision',label:'奪った後の前進判断',options:[UNKNOWN,'前方のスペースへ運んだ','前方の味方へパス','サイドのスペースを使った','縦パスを選んだ','安全な横・後方パス','無理に運ばず保持','前進判断が確認できない']},
{id:'nextOutcome',label:'切り替え後の結果',options:[UNKNOWN,'ボールを奪い返した','相手の前進を止めた','味方がボールを保持した','前進・攻撃につながった','シュート機会につながった','相手に前進された','ボールを失った']}
];
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function data(){if(typeof state==='undefined')return null;state.transitionAnalysisRecords=Array.isArray(state.transitionAnalysisRecords)?state.transitionAnalysisRecords:[];return state;}
function verifiedScenes(){
 const s=data();if(!s)return [];
 const out=[];
 (s.matchAnalyses||[]).forEach(m=>(m.candidateEvents||[]).forEach(e=>{
  if(e.reviewLabel==='陸玖'&&e.tacticalReview&&e.tacticalReview.reviewedAt)out.push({match:m,event:e});
 }));
 return out;
}
function sceneKey(x){return String(x.match.id)+'|'+String(x.event.id);}
function mount(){
 const anchor=document.getElementById('rikuTacticalAnalysisPanel');if(!anchor||document.getElementById(ID))return;
 const p=document.createElement('section');p.id=ID;p.className='card';
 p.innerHTML='<h2>専門分析｜攻守の切り替え</h2><p class="tiny muted">試合動画を確認し、陸玖本人と手動確認済みの場面だけを使います。既存の試合中判断分析で保存した場面を選択し、見える事実だけ記録してください。</p>'+
 '<label class="label">本人確認・分析保存済みの試合場面<select id="trScene"><option value="">場面を選択</option></select></label>'+
 '<div class="two"><label class="label">切り替えの種類<select id="trType"><option value="ボールを失った直後（攻撃→守備）">ボールを失った直後（攻撃→守備）</option><option value="ボールを奪った直後（守備→攻撃）">ボールを奪った直後（守備→攻撃）</option></select></label><label class="label">カメラ角度<select id="trAngle"><option>斜め後方</option><option>横</option><option>正面</option><option>斜め前</option><option>高い位置・俯瞰</option><option>未確認</option></select></label></div>'+
 '<div class="two"><label class="label">カメラからの距離<select id="trDistance"><option>近距離</option><option>中距離</option><option>遠距離</option><option>未確認</option></select></label><label class="label">映像の写り方<select id="trFraming"><option>陸玖とボール・周囲が見える</option><option>陸玖とボールが見える</option><option>陸玖のみ見える</option><option>ボールが隠れる</option><option>周囲が映らない</option><option>未確認</option></select></label></div>'+
 '<div class="two">'+groups.map(g=>'<label class="label">'+esc(g.label)+'<select data-tr-field="'+g.id+'">'+g.options.map(v=>'<option>'+esc(v)+'</option>').join('')+'</select></label>').join('')+'</div>'+
 '<label class="label">映像で確認したこと・場面メモ（任意）<textarea id="trNote" maxlength="400" placeholder="例：ボールを失った直後、中央側へ戻ってパスコースを切った。"></textarea></label>'+
 '<div class="btnrow"><button type="button" id="trSave">切り替え分析を保存</button><button type="button" class="secondary" id="trClear">入力をリセット</button></div><div id="trStatus" class="tiny muted"></div>'+
 '<div class="divider"></div><h3>同じ撮影条件での比較</h3><div id="trCompare" class="tiny muted">同条件3件以上で傾向を表示します。</div>'+
 '<div class="divider"></div><h3>陸玖専用・改善練習</h3><div id="trPractice" class="tiny muted">記録が集まるまでは評価保留です。</div>'+
 '<div class="divider"></div><h3>保存した切り替え分析</h3><div id="trRecords"></div>';
 anchor.insertAdjacentElement('afterend',p);
 p.querySelector('#trSave').addEventListener('click',save);
 p.querySelector('#trClear').addEventListener('click',()=>{p.querySelectorAll('[data-tr-field]').forEach(x=>x.selectedIndex=0);p.querySelector('#trNote').value='';});
}
function fillScenes(){
 const p=document.getElementById(ID),sel=p&&p.querySelector('#trScene');if(!sel)return;
 const old=sel.value,rows=verifiedScenes();
 sel.innerHTML='<option value="">場面を選択</option>'+rows.map(x=>'<option value="'+esc(sceneKey(x))+'">'+esc(x.match.date||'日付不明')+'｜'+esc(x.match.title||'試合動画')+'｜'+esc(typeof formatMatchTime==='function'?formatMatchTime(x.event.time):x.event.time)+'｜'+esc(x.event.actionType||x.event.label||'確認場面')+'</option>').join('');
 if(rows.some(x=>sceneKey(x)===old))sel.value=old;
}
function save(){
 const s=data(),p=document.getElementById(ID),scene=p.querySelector('#trScene').value,src=verifiedScenes().find(x=>sceneKey(x)===scene);
 if(!src){alert('先に試合場面を「陸玖本人」として確認し、試合中判断分析を保存してください。');return;}
 const fields={};groups.forEach(g=>fields[g.id]=p.querySelector('[data-tr-field="'+g.id+'"]').value);
 const setup={transitionType:p.querySelector('#trType').value,cameraAngle:p.querySelector('#trAngle').value,distance:p.querySelector('#trDistance').value,framing:p.querySelector('#trFraming').value};
 const r={id:Date.now(),date:src.match.date|| (typeof today==='function'?today():new Date().toISOString().slice(0,10)),matchId:src.match.id,eventId:src.event.id,matchTitle:src.match.title||'試合動画',eventTime:src.event.time,setup,fields,note:p.querySelector('#trNote').value.trim().slice(0,400),reviewedAt:new Date().toISOString()};
 s.transitionAnalysisRecords.unshift(r);if(typeof persist==='function')persist();
 p.querySelector('#trStatus').textContent='保存しました。手動確認済みの試合場面に紐づけました。';alert('攻守の切り替え分析を保存しました。');
}
function setupKey(x){const q=x.setup||{};return [q.transitionType,q.cameraAngle,q.distance,q.framing].join('|');}
function suggestions(rows){
 const out=[];
 const add=(id,bad,title,drill)=>{const hits=rows.filter(r=>r.fields&&bad.includes(r.fields[id]));if(hits.length>=2)out.push({count:hits.length,title,drill,reason:'同条件で「'+hits[0].fields[id]+'」が'+hits.length+'回確認されています。'});};
 add('lossReaction',['守備への切り替えが遅れた','反応が確認できない'],'ボールを失った直後の一歩','親子で1対1。合図でボールを失った想定にし、最初の2〜3歩でボール方向へ寄せるか中央を切るかを選ぶ。左右各5回。');
 add('firstSteps',['立ち止まった・反応が遅れた'],'切り替え直後の初速','合図と同時に最初の3歩を全力で動く。攻撃→守備、守備→攻撃を交互に各5回。');
 add('press',['プレスに行かなかった','プレス状況が確認できない'],'相手の前進を遅らせるプレス','相手役がボールを持った瞬間に寄せ、奪い切れなくても中央・前進コースを限定する。5回。');
 add('cover',['味方と役割が重なった','カバーが確認できない'],'味方を助けるカバーリング','親子2人でボール役と守備役。1人が寄せ、もう1人が中央・背後をカバーする動きを反復。');
 add('recoveryDirection',['ボールだけを追いかけた','戻る動きが確認できない'],'ゴール方向を意識した戻り','ボールを失った合図で、ボールとゴールの間に入るコースを斜めに走って戻る。左右各5回。');
 add('gainReaction',['奪った後の反応が確認できない'],'奪った直後の前方確認','ボールを奪った想定で顔を上げ、前・横・後ろの出口を確認してからプレーを選ぶ。6回。');
 add('progressDecision',['安全な横・後方パス','無理に運ばず保持','前進判断が確認できない'],'奪った後の前進判断','ボール奪取後に前方のゲートが空いていれば運ぶ、味方が空いていればパスする判断練習。6回。');
 return out;
}
function render(){
 const s=data(),p=document.getElementById(ID);if(!s||!p)return;fillScenes();
 const records=s.transitionAnalysisRecords||[],list=p.querySelector('#trRecords'),cmp=p.querySelector('#trCompare'),prac=p.querySelector('#trPractice');
 if(!records.length){list.innerHTML='<div class="tiny muted">まだ分析記録はありません。</div>';cmp.textContent='同じ切り替え種類・角度・距離・写り方の記録が3件以上集まると比較します。';prac.textContent='本人確認済みの試合場面を選んで記録してください。';return;}
 list.innerHTML=records.slice(0,12).map(r=>{const known=groups.filter(g=>r.fields&&r.fields[g.id]&&r.fields[g.id]!==UNKNOWN).length;return '<div class="listitem"><div class="grow"><b>'+esc(r.date)+'｜'+esc(r.matchTitle)+'</b><div class="tiny muted">'+esc(r.setup.transitionType)+'｜'+esc(r.setup.cameraAngle)+'・'+esc(r.setup.distance)+'・確認 '+known+'/'+groups.length+'項目</div><div class="tiny">最初の数歩：'+esc(r.fields.firstSteps)+'／プレス：'+esc(r.fields.press)+'／前進判断：'+esc(r.fields.progressDecision)+'</div>'+(r.note?'<div class="tiny muted">'+esc(r.note)+'</div>':'')+'</div><button type="button" class="danger small" data-tr-del="'+r.id+'">削除</button></div>';}).join('');
 list.querySelectorAll('[data-tr-del]').forEach(b=>b.addEventListener('click',()=>{if(!confirm('この分析記録を削除しますか？'))return;s.transitionAnalysisRecords=s.transitionAnalysisRecords.filter(x=>String(x.id)!==b.dataset.trDel);if(typeof persist==='function')persist();render();}));
 const latest=records[0],rows=records.filter(r=>setupKey(r)===setupKey(latest)),q=latest.setup;
 if(rows.length<3){cmp.innerHTML='<div class="tiny muted">比較条件：'+esc(q.transitionType)+'｜'+esc(q.cameraAngle)+'｜'+esc(q.distance)+'｜'+esc(q.framing)+'</div><div class="note">評価保留：同条件 '+rows.length+'件。あと'+(3-rows.length)+'件で傾向を表示します。</div>';prac.textContent='同条件の記録が3件に達するまでは課題を断定しません。';return;}
 const summary=groups.map(g=>{const counts={};rows.forEach(r=>{const v=r.fields&&r.fields[g.id];if(v&&v!==UNKNOWN)counts[v]=(counts[v]||0)+1;});const text=Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(x=>esc(x[0])+' '+x[1]+'回').join('／')||'確認できた記録なし';return '<div class="tiny"><b>'+esc(g.label)+'</b>：'+text+'</div>';}).join('');
 cmp.innerHTML='<div class="tiny muted">比較条件：'+esc(q.transitionType)+'｜'+esc(q.cameraAngle)+'｜'+esc(q.distance)+'｜'+esc(q.framing)+'｜'+rows.length+'件</div><div class="tiny muted">手動確認した観察内容の集計です。映像にない情報は集計せず、成功率や能力を自動判定しません。</div>'+summary;
 const ideas=suggestions(rows).sort((a,b)=>b.count-a.count);
 if(!ideas.length){prac.textContent='同条件で繰り返し確認された改善課題はありません。別の場面も記録して比較しましょう。';return;}
 prac.innerHTML=ideas.slice(0,4).map(x=>'<div class="note"><b>'+esc(x.title)+'</b><div class="tiny">'+esc(x.reason)+'</div><div class="tiny"><b>練習：</b>'+esc(x.drill)+'</div><button type="button" class="secondary small" data-tr-plan="'+esc(x.title)+'" data-tr-drill="'+esc(x.drill)+'">今日の練習に設定</button></div>').join('');
 prac.querySelectorAll('[data-tr-plan]').forEach(b=>b.addEventListener('click',()=>{const name=b.dataset.trPlan,drill=b.dataset.trDrill;s.menus=Array.isArray(s.menus)?s.menus:[];if(!s.menus.some(x=>x.name===name))s.menus.unshift({name,category:'受ける動き',minutes:10});if(typeof persist==='function')persist();const menu=document.getElementById('trainMenu');if(menu)menu.value=name;const focus=document.getElementById('trainFocus');if(focus)focus.value='ボールを受ける';const note=document.getElementById('trainNote');if(note)note.value=drill;if(typeof showView==='function')showView('training');}));
}
function install(){if(typeof state==='undefined')return;mount();render();if(typeof window.renderAll==='function'&&!window.renderAll.__transitionWrapped){const original=window.renderAll;const wrapped=function(){const result=original.apply(this,arguments);render();return result;};wrapped.__transitionWrapped=true;window.renderAll=wrapped;}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuTransitionAnalysis=render;
})();