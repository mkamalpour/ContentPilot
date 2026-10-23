"""Identity ownership checks run the real frontend helper without browser/network."""
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize("case", ["same_topic", "matching_id", "unknown_id", "valid_body"])
def test_incomplete_response_never_substitutes_unrelated_draft(case):
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional Node runtime unavailable for frontend unit checks")
    source = (Path(__file__).resolve().parents[1] / "templates/static/main.js").read_text(encoding="utf-8")
    function = source[source.index("  function recoverDraftBody"):source.index("  function unwrapDraft")]
    code = """
const assert = require('node:assert/strict');
FUNCTION
const library=[{id:1,topic:'same topic',body:'old draft'}, {id:2,topic:'same topic',body:'correct draft'}];
let record={topic:'same topic',body:''};
if(CASE==='matching_id') record.id=2;
if(CASE==='unknown_id') record.id=99;
if(CASE==='valid_body') record.body='response body';
const before=JSON.stringify(record);
const result=recoverDraftBody(record,library);
assert.equal(result.body,CASE==='matching_id'?'correct draft':CASE==='valid_body'?'response body':'');
assert.equal(JSON.stringify(record),before);
assert.equal(library[0].body,'old draft');
""".replace("FUNCTION", function).replace("CASE", repr(case))
    result = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_slow_older_library_refresh_cannot_replace_newer_results():
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional Node runtime unavailable for frontend unit checks")
    source = (Path(__file__).resolve().parents[1] / "templates/static/main.js").read_text(encoding="utf-8")
    function = source[source.index("  async function loadLibrary"):source.index("  function renderLibrary")]
    code = """
const assert=require('node:assert/strict');
let libraryRequest=0,contents=[],calls=0,renders=0,release;
const $=()=>({textContent:''});const notice=()=>{};const renderLibrary=()=>{renders++;};
const request=()=>++calls===1?new Promise(resolve=>{release=resolve;}):Promise.resolve([{id:2,body:'new'}]);
FUNCTION
(async()=>{
 const older=loadLibrary();await loadLibrary();release([{id:1,body:'old'}]);await older;
 assert.deepEqual(contents,[{id:2,body:'new'}]);assert.equal(renders,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""".replace("FUNCTION",function)
    result=subprocess.run([node,"-e",code],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
