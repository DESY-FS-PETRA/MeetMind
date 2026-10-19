import unittest
from unittest.mock import AsyncMock, patch

from app.services.conference_service import ConferenceService


class _DummyStorage:
    pass


class XRMParserRegressionTests(unittest.TestCase):
    def setUp(self):
        self.service = ConferenceService(_DummyStorage())

    def test_holozip_title_does_not_swallow_holographic_data_into_speaker(self):
        html = '''
        <div>ROOM: Auditorium 11:00 - 13:00 New meth - software 11:00 - 13:00 Chair: X</div>
        <div>12:45 - 13:00 4DPP - HoloZip: AI-Driven Extreme Compression for X-ray Holographic Data Vahid Rahmani - Deutsches Elektronen-Synchrotron</div>
        '''
        talks = self.service._parse_program_html(html, conference_start_date="2026-09-03")
        self.assertEqual(len(talks), 1)
        self.assertEqual(talks[0]["title"], "HoloZip: AI-Driven Extreme Compression for X-ray Holographic Data")
        self.assertEqual(talks[0]["speaker"], "Vahid Rahmani")
        self.assertEqual(talks[0]["institution"], "Deutsches Elektronen-Synchrotron")


class DetailClientLifecycleRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_enrichment_runs_while_client_is_open(self):
        service = ConferenceService(_DummyStorage())
        talks = [{"external_id":"4DPP", "title":"HoloZip", "keywords":[], "context_terms":[]}]
        main = AsyncMock(); main.text='<a href="detail.php?id=4DPP">4DPP</a>'; main.raise_for_status=lambda: None
        detail = AsyncMock(); detail.text='<h3>Abstract</h3><p>This is a sufficiently long abstract about HoloZip compression and scientific reconstruction fidelity for testing.</p>'; detail.raise_for_status=lambda: None

        class FakeClient:
            closed=False
            async def __aenter__(self): return self
            async def __aexit__(self,*a): self.closed=True
            async def get(self,url):
                if self.closed: raise RuntimeError('client closed')
                return detail if 'detail.php' in url else main

        service.get=lambda _id: {"start_date":"2026-09-03"}
        service._parse_program_html=lambda *_a, **_k: talks
        service.bulk_import=lambda *_a, **_k: {"talks": talks}
        class _Sess:
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def get(self,*a): return None
        service.storage=type('S',(),{'database':type('D',(),{'session_factory':type('F',(),{'begin':lambda self:_Sess()})()})()})()

        with patch('app.services.conference_service.httpx.AsyncClient', return_value=FakeClient()):
            out=await service.import_program_url('c1','https://example.test/show.php')
        self.assertIn('abstract', talks[0])
        self.assertTrue(talks[0]['abstract'].startswith('This is a sufficiently long abstract'))


if __name__ == '__main__':
    unittest.main()
