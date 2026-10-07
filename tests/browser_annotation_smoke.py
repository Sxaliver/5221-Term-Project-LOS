"""Optional UI smoke: python tests/browser_annotation_smoke.py (requires Playwright)."""
import base64,json,sys,shutil,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from traffic_los.annotation import make_html
from traffic_los.core import validate
from playwright.sync_api import sync_playwright
jpeg=base64.b64decode('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD26iiigD//2Q==')
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,**({'executable_path':shutil.which('chromium')} if shutil.which('chromium') else {}));page=b.new_page(viewport={'width':1250,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.set_content(make_html(jpeg,720,576));c=page.locator('#canvas')
 assert page.locator('#road,#lane,#heading').count()==0
 page.locator('#origin').select_option('N');assert page.locator('#name').input_value()=='from_N_entry'
 c.click(position={'x':100,'y':100});c.click(position={'x':300,'y':100});page.locator('#pickDirection').click();c.click(position={'x':200,'y':160});page.locator('#add').click()
 assert page.evaluate('scene.lines[0].origin_side')=='N';assert page.locator('#name').input_value()=='from_N_entry_2'
 own=page.evaluate('JSON.stringify(scene.lines[0])')
 imp={'schema_version':1,'width':720,'height':576,'lines':[{'name':'from_N_entry','role':'count','heading':'EB','points':[[100,200],[300,200]]},{'name':'another','points':[[100,300],[300,300]]}],'zones':[{'name':'ped_area','classes':['person'],'points':[[400,100],[500,100],[500,200],[400,200]]}]}
 with page.expect_file_chooser() as fc:page.locator('#importButton').click()
 fc.value.set_files({'name':'scene.json','mimeType':'application/json','buffer':json.dumps(imp).encode()})
 page.wait_for_function('scene.lines.length===3')
 assert page.evaluate('JSON.stringify(scene.lines[0])')==own
 assert page.evaluate('scene.lines[1].name')=='from_N_entry_2'
 assert page.locator('#items li.imported').count()==3
 assert '来自西侧' in page.locator('#items li').nth(1).inner_text()
 validate(page.evaluate('scene'))
 page.locator('#undo').click();assert page.evaluate('scene.lines.length===1 && scene.zones.length===0');assert page.evaluate('JSON.stringify(scene.lines[0])')==own
 page.locator('#load').set_input_files({'name':'scene.json','mimeType':'application/json','buffer':json.dumps(imp).encode()});page.wait_for_function('scene.lines.length===3')
 c.click(button='right',position={'x':200,'y':200});assert page.locator('#add').inner_text()=='保存修改';assert page.locator('#origin').input_value()=='W';page.locator('#name').fill('from_W_count');page.locator('#add').click()
 assert page.evaluate("scene.lines.some(x=>x.name==='from_W_count' && x.annotation_source==='imported' && x.origin_side==='W')")
 assert page.locator('#items li.imported').count()==3
 page.locator('#undo').click();assert page.evaluate("scene.lines.some(x=>x.name==='from_N_entry_2' && x.heading==='EB')")
 page.set_viewport_size({'width':520,'height':950});box=c.bounding_box();c.click(button='right',position={'x':200*box['width']/720,'y':300*box['height']/576});assert page.locator('#name').input_value()=='another';page.locator('#clear').click()
 before=page.evaluate('JSON.stringify(scene)');bad={**imp,'width':12};page.locator('#load').set_input_files({'name':'bad.json','mimeType':'application/json','buffer':json.dumps(bad).encode()});page.wait_for_function("document.getElementById('message').textContent.includes('导入失败')");assert page.evaluate('JSON.stringify(scene)')==before
 with page.expect_download() as d:page.locator('#save').click()
 with tempfile.TemporaryDirectory(prefix='annotation-download-') as folder:
  f=Path(folder)/'scene.json';d.value.save_as(f);validate(json.loads(f.read_text()))
  assert json.loads(f.read_text())['lines'][1]['annotation_source']=='imported'
 page.set_viewport_size({'width':1250,'height':1000})
 assert not errors,errors
 print('PASS: origin naming, removed unused controls, button-based append, collision rename, original preservation, import badge, whole-import undo, right-click edit, legacy conversion, provenance persistence, edit undo, scaled hit detection, rejected import atomicity, downloaded backend validation')
 b.close()
