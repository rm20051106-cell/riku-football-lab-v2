(function(){
'use strict';
const ID='rikuFirstTouchPanel';
const UNKNOWN='映像で確認できない';
const fields=[
{id:'scan',label:'受ける前の準備・首振り',options:[UNKNOWN,'左右を確認した','片側を確認した','ボールだけを見ていた','確認動作が見えない']},
{id:'body',label:'身体の向き',options:[UNKNOWN,'半身で前を向ける','正面を向いて受けた','背中を向けて受けた','身体が閉じていた','受ける直前に向きを変えた']},
{id:'touchPlacement',label:'ボールを置いた位置',options:[UNKNOWN,'前方へ置けた','身体の近くに置けた','相手から遠い側へ置けた','足元に止まりすぎた','相手に近い側へ置いた','身体から離れすぎた']},
{id:'touchDirection',label:'ファーストタッチの方向',options:[UNKNOWN,'前方','斜め前','横方向','後方','相手から遠ざけた','相手方向へ運んだ','止めた・動かさなかった']},
{id:'opponentDistance',label:'受けた瞬間の相手との距離',options:[UNKNOWN,'密着・すぐ奪いに来る','約1歩','約2〜3歩','十分に離れている','相手が画面に映っていない']},
{id:'nextPlay',label:'ファーストタッチ後のプレー',options:[UNKNOWN,'前進ドリブル','パス','シュート','クロス','キープして次を探す','ターン','ボールを失った','相手に奪われる前にクリア']},
{id:'pressure',label:'受けた時のプレッシャー',options:[UNKNOWN,'正面から','背後から','横から','複数方向','プレッシャーなし']},
{id:'outcome',label:'タッチ後の状態',options:[UNKNOWN,'前を向いて保持','次のプレーにつながった','味方へ安全につないだ','相手に奪われた','タッチが大きくなった','判定できない']}
];
const extra=[
{id:'distance',label:'カメラからの距離',options:['近距離','中距離','遠距離','未確認']},
{id:'framing',label:'映像の写り方',options:['全身とボールが見える','選手とボールが見える','足元中心','相手が見えない','ボールが隠れる','その他']}
];
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function getState(){if(typeof state==='undefined')return null;state.firstTouchRecords=Array.isArray(state.firstTouchRecords)?state.firstTouchRecords:[];return state;}
function mount(){
 const kind=document.getElementById('formKind');
 if(kind&&!Array.from(kind.options).some(x=>x.value==='ファーストタッチ')){const o=document.createElement('option');o.value='ファーストタッチ';o.textContent='ファーストタッチ';kind.appendChild(o);}
 const anchor=document.getElementById('rikuShootingSpecialistPanel');
 if(!anchor||document.getElementById(ID))return;
 const panel=document.createElement('div');panel.className='card';panel.id=ID;
 panel.innerHTML='<h2>専門分析｜ファーストタッチ・ボールの置き所</h2>'+
 '<p class="tiny muted">先に「ファーストタッチ」種別でフォーム動画を保存してください。その動画を選び、再生・一時停止しながら見える項目だけ記録します。未確認は評価保留のまま保存できます。</p>'+
 '<label class="label">分析する保存動画</label><select id="ftSource"><option value="">保存済みファーストタッチ動画を選択</option></select>'+
 '<div class="two"><label class="label">カメラからの距離<select data-ft-extra="distance">'+extra[0].options.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select></label><label class="label">映像の写り方<select data-ft-extra="framing">'+extra[1].options.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select></label></div>'+
 '<div class="two">'+fields.map(f=>'<label class="label">'+esc(f.label)+'<select data-ft-field="'+f.id+'">'+f.options.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select></label>').join('')+'</div>'+
 '<label class="label">映像で確認したこと・場面メモ（任意）<textarea id="ftNote" maxlength="300" placeholder="例：右側から相手が寄せてきた。左足側へ置いた場面を確認。"></textarea></label>'+
 '<div class="btnrow"><button type="button" id="ftSave">分析を保存</button><button type="button" class="secondary" id="ftReset">入力をリセット</button></div><div id="ftStatus" class="tiny muted"></div>'+
 '<div class="divider"></div><h3>同じ撮影条件での比較</h3><div id="ftCompare" class="tiny muted">同条件3件以上で傾向を表示します。</div>'+
 '<div class="divider"></div><h3>陸玖専用・改善練習</h3><div id="ftPractice" class="tiny muted">十分な記録が集まるまでは評価保留です。</div>'+
 '<div class="divider"></div><h3>保存した分析記録</h3><div id="ftRecords"></div>';
 anchor.insertAdjacentElement('afterend',panel);
 panel.querySelector('#ftSave').addEventListener('click',save);
 panel.querySelector('#ftReset').addEventListener('click',()=>{panel.querySelectorAll('[data-ft-field],[data-ft-extra]').forEach(x=>x.selectedIndex=0);panel.querySelector('#ftNote').value='';});
}
function sourceMeta(form){const p=document.getElementById(ID);return {kind:form.kind,foot:form.foot,cameraAngle:form.cameraAngle||'未選択',distance:p.querySelector('[data-ft-extra="distance"]').value,framing:p.querySelector('[data-ft-extra="framing"]').value};}
function key(m){return [m.kind,m.foot,m.cameraAngle,m.distance,m.framing].join('|');}
function refreshSourceOptions(){
 const s=getState(),sel=document.getElementById('ftSource');if(!s||!sel)return;
 const old=sel.value,forms=(s.forms||[]).filter(x=>x.kind==='ファーストタッチ');
 sel.innerHTML='<option value="">保存済みファーストタッチ動画を選択</option>'+forms.map(x=>'<option value="'+esc(x.id)+'">'+esc(x.date)+'｜'+esc(x.title)+'｜'+esc(x.cameraAngle||'未選択')+(x.hasVideo?'（動画あり）':'（動画未保存）')+'</option>').join('');
 if(forms.some(x=>String(x.id)===old))sel.value=old;
}
function save(){
 const s=getState(),p=document.getElementById(ID),sel=p.querySelector('#ftSource'),form=(s.forms||[]).find(x=>String(x.id)===sel.value);
 if(!form){alert('先に「ファーストタッチ」種別で動画を保存し、分析対象を選択してください。');return;}
 const values={};fields.forEach(f=>values[f.id]=p.querySelector('[data-ft-field="'+f.id+'"]').value);
 const meta=sourceMeta(form),record={id:Date.now(),date:typeof today==='function'?today():new Date().toISOString().slice(0,10),title:form.title,sourceFormId:form.id,kind:form.kind,foot:form.foot,cameraAngle:meta.cameraAngle,setup:meta,fields:values,note:p.querySelector('#ftNote').value.trim().slice(0,300),reviewedAt:new Date().toISOString()};
 s.firstTouchRecords.unshift(record);if(typeof persist==='function')persist();p.querySelector('#ftStatus').textContent='保存しました。元動画「'+form.title+'」に紐づけました。';alert('ファーストタッチ分析を保存しました。');
}
function sameSetup(a,b){return key(a.setup||a)===key(b.setup||b);}
function count(rows){const out={};fields.forEach(f=>{out[f.id]={};rows.forEach(r=>{const v=r.fields&&r.fields[f.id];if(v&&v!==UNKNOWN)out[f.id][v]=(out[f.id][v]||0)+1;});});return out;}
function suggestions(c){
 const out=[];
 function add(id,bad,title,drill){const pair=Object.entries(c[id]).filter(x=>bad.includes(x[0])).sort((a,b)=>b[1]-a[1])[0];if(pair&&pair[1]>=2)out.push({n:pair[1],title,drill,reason:'同じ条件で「'+pair[0]+'」が'+pair[1]+'回確認されています。'});}
 add('scan',['ボールだけを見ていた'],'受ける前の確認を習慣化','親子でパス交換。ボールが出る前に左右どちらかを確認し、声に出してから受ける。左右各5回。');
 add('body',['正面を向いて受けた','背中を向けて受けた','身体が閉じていた'],'半身で受ける準備','マーカーを相手役にして、半身で構えて受ける。受ける前に肩越し確認を入れ、左右各5回。');
 add('touchPlacement',['足元に止まりすぎた','相手に近い側へ置いた','身体から離れすぎた'],'次のプレーにつながる置き所','左右にゲートを作り、パスを受けたら相手役から遠い側へ1歩分のタッチ。左右各5回。');
 add('touchDirection',['後方','相手方向へ運んだ','止めた・動かさなかった'],'相手とスペースを見た方向づけ','親子1対1。受ける直前に左右を見て、空いたゲートへファーストタッチ。左右交互に6回。');
 add('opponentDistance',['密着・すぐ奪いに来る','約1歩'],'プレッシャー下のファーストタッチ','相手役が近づくタイミングでパス。相手から遠い足・方向へタッチして、2タッチ目でパス。5回。');
 add('nextPlay',['ボールを失った','相手に奪われる前にクリア'],'タッチ後の次のプレーを早く選ぶ','受ける前に「前・横・後ろ」の出口を確認。受けた後2タッチ以内でドリブルかパスを選ぶ。6回。');
 return out;
}
function render(){
 const s=getState(),p=document.getElementById(ID);if(!s||!p)return;refreshSourceOptions();
 const records=s.firstTouchRecords||[],list=p.querySelector('#ftRecords'),compare=p.querySelector('#ftCompare'),practice=p.querySelector('#ftPractice');
 if(!records.length){list.innerHTML='<div class="tiny muted">まだ分析記録はありません。</div>';compare.textContent='同じ撮影条件の記録が3件以上集まると比較できます。';practice.textContent='ファーストタッチ動画を保存し、見える項目から記録してください。';return;}
 list.innerHTML=records.slice(0,10).map(r=>{const known=fields.filter(f=>r.fields&&r.fields[f.id]&&r.fields[f.id]!==UNKNOWN).length;return '<div class="listitem"><div class="grow"><b>'+esc(r.date)+'｜'+esc(r.title)+'</b><div class="tiny muted">'+esc(r.cameraAngle)+'・'+esc(r.setup.distance)+'・確認 '+known+'/'+fields.length+'項目</div><div class="tiny">準備：'+esc(r.fields.scan)+'／向き：'+esc(r.fields.body)+'／タッチ：'+esc(r.fields.touchDirection)+'／次：'+esc(r.fields.nextPlay)+'</div>'+(r.note?'<div class="tiny muted">'+esc(r.note)+'</div>':'')+'<button type="button" class="secondary small" data-ft-play="'+esc(r.sourceFormId)+'">元動画を再生</button></div><button type="button" class="danger small" data-ft-del="'+r.id+'">削除</button></div>';}).join('');
 list.querySelectorAll('[data-ft-del]').forEach(b=>b.addEventListener('click',()=>{if(!confirm('この分析記録を削除しますか？'))return;s.firstTouchRecords=s.firstTouchRecords.filter(x=>String(x.id)!==b.dataset.ftDel);if(typeof persist==='function')persist();render();}));
 list.querySelectorAll('[data-ft-play]').forEach(b=>b.addEventListener('click',()=>{if(typeof playSavedForm==='function')playSavedForm(Number(b.dataset.ftPlay));}));
 const latest=records[0],rows=records.filter(r=>sameSetup(r,latest)),m=latest.setup||latest,setupText=[m.kind,m.foot,m.cameraAngle,m.distance,m.framing].join('｜');
 if(rows.length<3){compare.innerHTML='<div class="tiny muted">比較条件：'+esc(setupText)+'</div><div class="note">評価保留：同条件 '+rows.length+'件。あと'+(3-rows.length)+'件集まるまで傾向を断定しません。</div>';practice.innerHTML='<div class="note">改善テーマは評価保留です。まず同じ条件で記録を増やしてください。</div>';return;}
 const c=count(rows),summary=fields.map(f=>{const vals=Object.entries(c[f.id]).sort((a,b)=>b[1]-a[1]);return '<div class="tiny"><b>'+esc(f.label)+'</b>：'+(vals.length?vals.map(x=>esc(x[0])+' '+x[1]+'回').join('／'):'確認できた記録なし')+'</div>';}).join('');
 compare.innerHTML='<div class="tiny muted">比較条件：'+esc(setupText)+'｜'+rows.length+'件</div><div class="tiny muted">記録された観察内容の集計です。プレーの良否を自動判定するものではありません。</div>'+summary;
 const ideas=suggestions(c).sort((a,b)=>b.n-a.n);
 if(!ideas.length){practice.innerHTML='<div class="note">繰り返し確認された課題はまだありません。今の準備とタッチを再現しながら記録を続けましょう。</div>';return;}
 practice.innerHTML=ideas.slice(0,3).map(x=>'<div class="note"><b>'+esc(x.title)+'</b><div class="tiny">'+esc(x.reason)+'</div><div class="tiny"><b>練習：</b>'+esc(x.drill)+'</div><button type="button" class="secondary small" data-ft-plan="'+esc(x.title)+'" data-ft-drill="'+esc(x.drill)+'">今日の練習に設定</button></div>').join('');
 practice.querySelectorAll('[data-ft-plan]').forEach(b=>b.addEventListener('click',()=>{const name=b.dataset.ftPlan,drill=b.dataset.ftDrill;s.menus=Array.isArray(s.menus)?s.menus:[];if(!s.menus.some(x=>x.name===name))s.menus.unshift({name,category:'受ける動き',minutes:10});if(typeof persist==='function')persist();const menu=document.getElementById('trainMenu');if(menu)menu.value=name;const focus=document.getElementById('trainFocus');if(focus)focus.value='ボールを受ける';const note=document.getElementById('trainNote');if(note)note.value=drill;if(typeof showView==='function')showView('training');}));
}
function install(){
 if(typeof state==='undefined')return;mount();render();
 const kind=document.getElementById('formKind');if(kind&&!kind.__ftBound){kind.__ftBound=true;kind.addEventListener('change',()=>{if(kind.value==='ファーストタッチ'){const note=document.getElementById('formNote');if(note&&!note.value)note.value='受ける前の準備、身体の向き、ファーストタッチを確認';}});}
 if(typeof window.renderAll==='function'&&!window.renderAll.__firstTouchWrapped){const original=window.renderAll;const wrapped=function(){const result=original.apply(this,arguments);render();return result;};wrapped.__firstTouchWrapped=true;window.renderAll=wrapped;}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuFirstTouch=render;
})();