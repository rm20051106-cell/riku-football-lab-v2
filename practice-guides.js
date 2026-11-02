(function(){
'use strict';
const ID='rikuPracticeGuideLibrary';
const UNKNOWN='記録・映像で未確認';
const GUIDES=[
{id:'dribble',name:'ドリブル突破・1対1',focus:'ドリブル',duration:12,level:'基礎→対人',aim:'相手の動きに合わせて運ぶ方向を選び、抜いた後も加速を続ける練習。',flow:['相手を見る','運ぶスピードを上げる','相手の重心と足を見る','左右・緩急でかわす','抜いた後の2〜3歩を加速'],steps:['マーカーを3つ、約2m間隔で置き、左右に運ぶ。左右各3往復。','親子で1対1。守備役は左右どちらかを空け、攻撃役は相手を見て選ぶ。左右各4回。','突破できたら止まらず、2〜3歩先のゲートまで運ぶ。4〜6回。','最後に守備役の動きを自由にして、同じ判断を試す。'],cues:['仕掛ける前に相手の足・重心を見る','ボールを足元に置きすぎず、次の一歩へ運ぶ','フェイントの後に進む方向へ身体を移す','抜いた後に減速せず、次のプレーへつなぐ'],checks:['相手の動きを見て左右を選べた','かわした後もボールを前へ運べた','突破後に次のパス・シュートを選べた'],improve:['相手を見ずに同じ方向へ行く','ボールが身体から離れすぎる','かわした後に止まってしまう'],diagram:'dribble',note:'狭い場所ではマーカー2つの間を通すだけでもOK。対人は接触せず、守備役は最初はゆっくり動かす。'},
{id:'shooting',name:'シュート・フリーキック',focus:'シュート',duration:12,level:'近距離→コース',aim:'助走・軸足・ボールへの当て方・狙うコースを一つずつ確認する。',flow:['狙う場所を決める','助走の角度とリズム','軸足をボールの横へ','ボールを蹴る','蹴った後にバランス'],steps:['ゴールを左右3つのコースに分け、蹴る前に狙いを声に出す。','近距離から力を抑えて5本。軸足の位置とつま先の向きを確認する。','助走を2〜3歩にそろえ、同じコースへ3本蹴る。','FKは壁役を置く場合も安全な距離を確保し、最初はコースと高さを決めて3本。'],cues:['最初は強さより狙った場所へ蹴ること','軸足はボールの横を目安に置く','蹴り足を狙う方向へ振り抜く','蹴った後に片足で大きく崩れないか確認'],checks:['狙うコースを蹴る前に決めた','助走の歩幅・リズムをそろえた','軸足の位置が毎回大きく変わらなかった','蹴った後にバランスを保てた'],improve:['助走の最後で歩幅が急に変わる','軸足がボールから離れすぎる／近すぎる','強く蹴ろうとして上体や軸が崩れる'],diagram:'shooting',note:'疲れてフォームが崩れたら本数を増やさず休憩。壁役に向けて強く蹴らない。'},
{id:'firsttouch',name:'ファーストタッチ・受ける前の準備',focus:'ボールを受ける',duration:10,level:'止める→前へ運ぶ',aim:'ボールが来る前に周囲を確認し、次のプレーがしやすい場所へボールを置く。',flow:['パスが出る前に見る','身体を半身にする','ボールの軌道を確認','遠い足・前方へ置く','次のパス・ドリブル'],steps:['親がパスを出す前に左右どちらかを指で示す。受け手は顔を上げて答える。左右各5回。','半身で構えて、足元へ来たボールを前方のゲートへコントロール。左右各5回。','ゲートを左右2つ置き、パス直前に親が示した側へファーストタッチ。各4回。','最後はタッチ後すぐにパスかドリブルを選ぶ。'],cues:['パスが出る前に一度は周囲を見る','身体を正面に固定せず半身で準備','相手がいる側から遠い足を使えるか試す','ボールを止めるだけでなく次の方向へ置く'],checks:['パス前に左右を確認できた','半身の姿勢で受けられた','次のプレー方向へタッチできた','タッチ後に顔を上げられた'],improve:['ボールが来てから周囲を見る','身体が閉じて次の方向へ進めない','ボールを足元に止めてしまう'],diagram:'firsttouch',note:'最初はゆっくり正確に。左右どちらの足でも試し、成功数より動作の確認を優先。'},
{id:'transition',name:'攻守の切り替え',focus:'守備・プレス',duration:10,level:'合図→判断',aim:'ボールを失った直後・奪った直後に、最初の行動を素早く選ぶ。',flow:['ボールを失う／奪う','最初の一歩を出す','守備は中央・前進路を意識','奪ったら前方を見る','次のプレーを選ぶ'],steps:['親の「ロスト」の合図で、ボールとゴールの間へ戻る。左右各4回。','親がボールを持ったら、飛び込まず前進コースを限定する。4〜6回。','「奪った」の合図で顔を上げ、前・横・後ろの出口を確認する。各4回。','最後に攻守の合図をランダムに出し、最初の行動を選ぶ。6回。'],cues:['ボールを失ったら立ち止まらず最初の一歩','一人で奪い切ろうとせずコースを限定','味方がいる想定でカバーする位置も意識','奪ったら急いで蹴らず前方の選択肢を見る'],checks:['合図の後にすぐ動き出せた','守備で中央や前進コースを意識できた','奪った後に前方を確認できた','状況に応じて運ぶ・パスを選べた'],improve:['ボールを失った後に止まる','相手へ一直線に飛び込む','奪った後に顔を上げず蹴ってしまう'],diagram:'transition',note:'全力ダッシュの連続にせず、1回ごとに歩いて戻って休む。2人で安全に行う。'},
{id:'positioning',name:'ポジショニング・サポート角度',focus:'オフザボール',duration:12,level:'立ち位置→動き出し',aim:'ボール保持者に対してパスコースを作り、相手の影から外れて受ける。',flow:['ボール保持者を見る','相手と味方の位置を見る','斜めの角度を作る','相手の視野の外へ動く','パスが出る前に準備'],steps:['親をボール保持者にして、正面ではなく斜め横に立つ場所を探す。左右各4回。','マーカーで三角形を作り、頂点を変えながらパスコースを作る。5往復。','親が顔を上げる前に一度動き、相手役の背後または横のスペースへ出る。左右各4回。','受けた後は前を向く・落とす・運ぶの3択から選ぶ。'],cues:['味方と同じ縦の線に重ならない','相手の背中や影から少し外れる','近づくだけでなく斜めのパス角度を作る','味方がパスを出せるタイミングで動く'],checks:['味方と相手の位置を見て立てた','パスコースが見える角度を作れた','味方が顔を上げる前後で動き出せた','受けた後の選択肢を持てた'],improve:['ボールに近づきすぎて味方と重なる','相手の後ろに隠れてパスコースがない','味方が出せないタイミングで走り出す'],diagram:'positioning',note:'2人でもマーカーを相手役にして練習可能。実戦では味方・相手・ゴールの位置で正解の場所が変わる。'}
];
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function stateData(){if(typeof state==='undefined')return null;state.menus=Array.isArray(state.menus)?state.menus:[];return state;}
let selected='dribble';
function diagram(type){
 const base='<svg viewBox="0 0 320 150" role="img" aria-label="練習動作の位置関係図" style="width:100%;max-width:440px;height:auto;background:#0b1524;border:1px solid #34475f;border-radius:12px"><rect x="10" y="10" width="300" height="130" rx="8" fill="#14283a" stroke="#56718a"/>';
 const dot=(x,y,c,label)=>'<circle cx="'+x+'" cy="'+y+'" r="8" fill="'+c+'"/><text x="'+(x+12)+'" y="'+(y+4)+'" fill="#eaf2fb" font-size="10">'+label+'</text>';
 const line=(x1,y1,x2,y2)=>'<path d="M'+x1+' '+y1+' L'+x2+' '+y2+'" stroke="#c8f169" stroke-width="3" fill="none" stroke-linecap="round" stroke-dasharray="5 4"/><path d="M'+(x2-7)+' '+(y2-4)+' L'+x2+' '+y2+' L'+(x2-8)+' '+(y2+3)+'" stroke="#c8f169" stroke-width="2" fill="none"/>';
 let content='';
 if(type==='dribble')content=dot(55,75,'#78c8ff','スタート')+dot(155,75,'#ffbd69','相手')+dot(260,42,'#c8f169','突破先')+line(65,75,140,75)+line(165,68,250,45);
 if(type==='shooting')content=dot(55,75,'#78c8ff','ボール')+dot(95,105,'#c8f169','軸足')+dot(160,75,'#ffbd69','キック')+'<rect x="260" y="40" width="34" height="70" fill="none" stroke="#c8f169" stroke-width="3"/>'+line(175,75,252,75);
 if(type==='firsttouch')content=dot(45,75,'#78c8ff','パス')+dot(145,75,'#ffbd69','受け手')+dot(250,38,'#c8f169','次の方向')+line(58,75,130,75)+line(155,68,238,42);
 if(type==='transition')content=dot(65,45,'#ffbd69','相手')+dot(120,100,'#78c8ff','ボール')+dot(250,100,'#c8f169','戻る位置')+line(128,100,235,100);
 if(type==='positioning')content=dot(65,75,'#78c8ff','保持者')+dot(155,35,'#ffbd69','相手')+dot(235,95,'#c8f169','サポート')+line(78,75,220,91);
 return base+content+'</svg>';
}
function render(){
 const s=stateData(),panel=document.getElementById(ID);if(!s||!panel)return;
 const filter=panel.querySelector('#pgFilter'),list=panel.querySelector('#pgGuideList'),detail=panel.querySelector('#pgGuideDetail');
 const term=filter.value.trim().toLowerCase();
 const visible=GUIDES.filter(g=>(g.name+' '+g.focus+' '+g.aim).toLowerCase().includes(term));
 if(!visible.some(g=>g.id===selected))selected=visible[0]?.id||'';
 list.innerHTML=visible.map(g=>'<button type="button" class="secondary small" data-guide="'+g.id+'" aria-pressed="'+(selected===g.id)+'" style="'+(selected===g.id?'border-color:#c8f169;color:#c8f169':'')+'">'+esc(g.name)+'</button>').join('')||'<div class="empty">該当する練習解説がありません。</div>';
 list.querySelectorAll('[data-guide]').forEach(b=>b.addEventListener('click',()=>{selected=b.dataset.guide;render();}));
 const g=GUIDES.find(x=>x.id===selected);
 if(!g){detail.innerHTML='';return;}
 detail.innerHTML='<div class="tag">'+esc(g.focus)+'</div><div class="tag">'+g.duration+'分の目安</div><div class="tag">'+esc(g.level)+'</div><h3 style="margin-top:8px">'+esc(g.name)+'</h3><p class="tiny">'+esc(g.aim)+'</p><h3>動きのお手本・位置関係</h3>'+diagram(g.diagram)+'<div class="tiny muted">矢印は動きの順序を示す簡易図です。実際の正解位置やフォームを自動判定するものではありません。</div><div class="divider"></div><h3>動きの流れ</h3><ol>'+g.flow.map(x=>'<li class="tiny" style="margin:5px 0">'+esc(x)+'</li>').join('')+'</ol><div class="divider"></div><h3>練習手順</h3><ol>'+g.steps.map(x=>'<li class="tiny" style="margin:7px 0">'+esc(x)+'</li>').join('')+'</ol><div class="divider"></div><h3>意識するポイント</h3>'+g.cues.map(x=>'<div class="checkrow"><span>• '+esc(x)+'</span></div>').join('')+'<div class="divider"></div><h3>成功の確認項目</h3>'+g.checks.map((x,i)=>'<label class="checkrow"><input type="checkbox" data-check="'+i+'"><span>'+esc(x)+'</span></label>').join('')+'<div class="divider"></div><h3>次回の改善チェック</h3>'+g.improve.map(x=>'<div class="tiny" style="margin:5px 0">・'+esc(x)+'</div>').join('')+'<div class="note">'+esc(g.note)+'</div><div class="btnrow"><button type="button" id="pgAddMenu">今日の練習メニューに追加</button></div><div class="tiny muted">チェック項目はこの画面での確認用です。自動で技術評価・合否判定は行いません。</div>';
 panel.querySelector('#pgAddMenu').addEventListener('click',()=>addToTraining(g));
}
function addToTraining(g){
 const s=stateData();if(!s)return;
 const name='お手本：'+g.name;
 let menu=s.menus.find(x=>x.name===name);
 if(!menu){menu={name,category:g.id==='dribble'?'突破・ドリブル':g.id==='shooting'?'シュート':g.id==='firsttouch'?'受ける動き':g.id==='transition'?'アジリティ':'受ける動き',minutes:g.duration};s.menus.unshift(menu);}
 const select=document.getElementById('trainMenu');if(select){if(typeof renderAll==='function')renderAll();select.value=name;}
 const focus=document.getElementById('trainFocus');if(focus)focus.value=g.focus;
 const minutes=document.getElementById('trainMinutes');if(minutes)minutes.value=g.duration;
 const note=document.getElementById('trainNote');if(note)note.value='【練習解説】'+g.name+'\n'+g.steps.map((x,i)=>(i+1)+'. '+x).join('\n')+'\n意識するポイント：'+g.cues.join('／');
 if(typeof persist==='function')persist();
 if(typeof showView==='function')showView('training');
}
function mount(){
 const host=document.getElementById('training'),intro=host&&host.querySelector('.section-desc');if(!host||!intro||document.getElementById(ID))return;
 const panel=document.createElement('section');panel.id=ID;panel.className='card';
 panel.innerHTML='<h2>お手本動画・練習解説</h2><p class="tiny muted">外部動画の実在性・権利・リンク切れを確認できないため、ここでは動きの順序を示す簡易図と文章で解説します。映像で見えない技術評価は行いません。</p><label class="label" for="pgFilter">練習テーマを検索</label><input id="pgFilter" placeholder="例：ドリブル、軸足、首振り、ポジショニング"><div id="pgGuideList" class="btnrow"></div><div class="divider"></div><div id="pgGuideDetail"></div>';
 intro.insertAdjacentElement('afterend',panel);
 panel.querySelector('#pgFilter').addEventListener('input',render);
}
function install(){
 if(!stateData())return;mount();render();
 if(typeof window.renderAll==='function'&&!window.renderAll.__practiceGuidesWrapped){
  const original=window.renderAll,wrapped=function(){const result=original.apply(this,arguments);render();return result;};
  wrapped.__practiceGuidesWrapped=true;window.renderAll=wrapped;
 }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuPracticeGuides=render;
})();