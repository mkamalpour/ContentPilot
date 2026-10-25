from contextlib import nullcontext
from types import SimpleNamespace
import pytest

from scraper import scraper
from database import publishing


def test_expired_download_budget_does_not_start_another_request(monkeypatch):
    clock=iter([0,41])
    monkeypatch.setattr(scraper.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(scraper,'validate_public_url',lambda url:pytest.fail('No work after deadline'))
    with pytest.raises(scraper.ScrapeError,match='time limit'):
        scraper.make_request('https://example.com')


def test_redirects_share_the_remaining_request_budget(monkeypatch):
    clock=iter([0,0,0,30,30])
    monkeypatch.setattr(scraper.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(scraper,'validate_public_url',lambda url:url)
    calls=[]
    redirect=SimpleNamespace(is_redirect=True,is_permanent_redirect=False,headers={'Location':'/next'})
    page=SimpleNamespace(is_redirect=False,is_permanent_redirect=False,headers={'Content-Type':'text/plain'},
                         raise_for_status=lambda:None,iter_content=lambda size:iter(()))
    class Client:
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            calls.append(kwargs['timeout']);return nullcontext(redirect if len(calls)==1 else page)
    monkeypatch.setattr(scraper.requests,'Session',Client)
    scraper.make_request('https://example.com')
    assert calls==[(5,20),(5,10)]


@pytest.mark.parametrize('payload',[{'id':True},{'id':0},{'id':'12'},[],{'id':12,'status':'unexpected'}])
def test_bad_wordpress_receipt_is_not_recorded_as_success(monkeypatch,payload):
    monkeypatch.setattr(publishing,'wordpress_configured',lambda:True)
    monkeypatch.setattr(publishing.config,'WORDPRESS_API_URL','https://example.com/wp-json/wp/v2/posts')
    response=SimpleNamespace(status_code=201,raise_for_status=lambda:None,json=lambda:payload)
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):return response
    monkeypatch.setattr(publishing.requests,'Session',Client)
    content=SimpleNamespace(wordpress_id=None,topic='Local article',body='Saved local text')
    with pytest.raises(ValueError,match='WordPress'):
        publishing.publish_content(content)
    assert content.wordpress_id is None and content.body=='Saved local text'
