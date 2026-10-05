import base64


def make_html(jpeg, width, height):
    """Self-contained local annotation UI: no server, external scripts or uploads."""
    page = '''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>路口区域标注</title>
<style>body{font:16px system-ui;margin:24px;background:#f6f7f9;color:#17202a}button,input,select{font:inherit;margin:5px;padding:6px}canvas{max-width:100%;height:auto;border:1px solid #888;cursor:crosshair}#status{white-space:pre-wrap}label{display:inline-block}</style>
<h1>路口区域标注</h1>
<p>选择类型并命名，在图上点击端点或多边形顶点，然后点击“添加”。标注坐标使用原图分辨率。浏览器中完成后下载 scene.json。</p>
<label>类型 <select id="type"><option value="entry">进口线 entry</option><option value="exit">出口线 exit</option><option value="count">普通计数线 count</option><option value="zone">区域 zone</option></select></label>
<label>名称 <input id="name" placeholder="例如 north_entry"></label>
<label>方向 <select id="direction"><option value="both">两个方向</option><option value="positive">negative → positive</option><option value="negative">positive → negative</option></select></label>
<label>类别 <input id="classes" placeholder="留空=全部；或 person,car"></label>
<button id="add">添加</button><button id="clear">清除当前点</button><button id="undo">撤销上一项</button><button id="save">下载 scene.json</button>
<p>线上的 + 标记表示 positive 侧。进口线和出口线应沿车辆行进方向先后穿越，配对结果为 entry → exit；具体左/直/右转需你依据路口方向解释。行人横道通常用普通计数线，类别设为 person。区域输出可见对象数，不直接代表排队长度。</p>
<canvas id="canvas" width="__WIDTH__" height="__HEIGHT__"></canvas><pre id="status"></pre>
<script>
const canvas=document.getElementById('canvas'),ctx=canvas.getContext('2d');
const image=new Image();image.src='data:image/jpeg;base64,__IMAGE__';
const scene={schema_version:1,width:canvas.width,height:canvas.height,lines:[],zones:[]};
let points=[],history=[];
const byId=id=>document.getElementById(id);
function drawItem(item,color,zone){
ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=3;ctx.beginPath();
item.points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));if(zone)ctx.closePath();ctx.stroke();
ctx.font='20px sans-serif';ctx.fillText(item.name,...item.points[0]);
if(!zone&&item.points.length===2){const [a,b]=item.points,dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy);if(len)ctx.fillText('+',(a[0]+b[0])/2-dy/len*20,(a[1]+b[1])/2+dx/len*20);}
item.points.forEach(p=>{ctx.beginPath();ctx.arc(...p,5,0,2*Math.PI);ctx.fill();});}
function redraw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);scene.lines.forEach(x=>drawItem(x,'#00ffb7',false));scene.zones.forEach(x=>drawItem(x,'#ffe55b',true));drawItem({name:'',points},'#ff5252',byId('type').value==='zone');byId('status').textContent=JSON.stringify(scene,null,2);}
image.onload=redraw;
canvas.onclick=e=>{const rect=canvas.getBoundingClientRect();points.push([Math.round((e.clientX-rect.left)*canvas.width/rect.width),Math.round((e.clientY-rect.top)*canvas.height/rect.height)]);redraw();};
byId('clear').onclick=()=>{points=[];redraw();};
byId('add').onclick=()=>{const type=byId('type').value,name=byId('name').value.trim(),zone=type==='zone';
if(!name||[...scene.lines,...scene.zones].some(x=>x.name===name))return alert('名称必须非空且唯一');
if(zone?points.length<3:points.length!==2)return alert(zone?'区域至少需要三个点':'线必须恰好两个点');
if(!zone&&points[0][0]===points[1][0]&&points[0][1]===points[1][1])return alert('线不能为零长度');
const item={name,points:points.map(p=>[...p])};
if(!zone){item.role=type;item.direction=byId('direction').value;const classes=byId('classes').value.split(',').map(x=>x.trim()).filter(Boolean);if(classes.length)item.classes=classes;}
const list=zone?'zones':'lines';scene[list].push(item);history.push(list);points=[];byId('name').value='';redraw();};
byId('undo').onclick=()=>{const list=history.pop();if(list)scene[list].pop();redraw();};
byId('save').onclick=()=>{if(!scene.lines.length&&!scene.zones.length)return alert('先添加一条线或区域');const blob=new Blob([JSON.stringify(scene,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='scene.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
</script></html>'''
    return page.replace('__WIDTH__', str(width)).replace('__HEIGHT__', str(height)).replace('__IMAGE__', base64.b64encode(jpeg).decode())
