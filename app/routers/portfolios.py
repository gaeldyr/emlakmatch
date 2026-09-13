import uuid
from typing import List
from fastapi import APIRouter, Request, Form, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import supabase
from app.utils.security import is_relationship_blocked
from app.utils.notifier import send_notification

router = APIRouter(prefix="/portfolios", tags=["Portfolios"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Türkiye 81 İl ve Eksiksiz İlçe Sözlüğü
TURKEY_DISTRICTS = {
    "Adana": ["Aladağ", "Ceyhan", "Çukurova", "Feke", "İmamoğlu", "Karaisalı", "Karataş", "Kozan", "Pozantı", "Saimbeyli", "Sarıçam", "Seyhan", "Tufanbeyli", "Yumurtalık", "Yüreğir"],
    "Adıyaman": ["Besni", "Çelikhan", "Gerger", "Gölbaşı", "Kahta", "Merkez", "Samsat", "Sincik", "Tut"],
    "Afyonkarahisar": ["Başmakçı", "Bayat", "Bolvadin", "Çay", "Çobanlar", "Dazkırı", "Dinar", "Emirdağ", "Evciler", "Hocalar", "İhsaniye", "İscehisar", "Kızılören", "Merkez", "Sandıklı", "Sinanpaşa", "Sultandağı", "Şuhut"],
    "Ağrı": ["Diyadin", "Doğubayazıt", "Eleşkirt", "Hamur", "Merkez", "Patnos", "Taşlıçay", "Tutak"],
    "Aksaray": ["Ağaçören", "Eskil", "Gülağaç", "Güzelyurt", "Merkez", "Ortaköy", "Sarıyahşi", "Sultanhanı"],
    "Amasya": ["Göynücek", "Gümüşhacıköy", "Hamamözü", "Merkez", "Merzifon", "Suluova", "Taşova"],
    "Ankara": ["Akyurt", "Altındağ", "Ayaş", "Bala", "Beypazarı", "Çamlıdere", "Çankaya", "Çubuk", "Elmadağ", "Etimesgut", "Evren", "Gölbaşı", "Güdül", "Haymana", "Kahramankazan", "Kalecik", "Keçiören", "Kızılcahamam", "Mamak", "Nallıhan", "Polatlı", "Pursaklar", "Sincan", "Şereflikoçhisar", "Yenimahalle"],
    "Antalya": ["Akseki", "Aksu", "Alanya", "Demre", "Döşemealtı", "Elmalı", "Finike", "Gazipaşa", "Gündoğmuş", "İbradı", "Kaş", "Kemer", "Kepez", "Konyaaltı", "Korkuteli", "Kumluca", "Manavgat", "Muratpaşa", "Serik"],
    "Ardahan": ["Çıldır", "Damal", "Göle", "Hanak", "Merkez", "Posof"],
    "Artvin": ["Ardanuç", "Arhavi", "Borçka", "Hopa", "Kemalpaşa", "Merkez", "Murgul", "Şavşat", "Yusufeli"],
    "Aydın": ["Bozdoğan", "Buharkent", "Çine", "Didim", "Efeler", "Germencik", "İncirliova", "Karacasu", "Karpuzlu", "Koçarlı", "Köşk", "Kuşadası", "Kuyucak", "Nazilli", "Söke", "Sultanhisar", "Yenipazar"],
    "Balıkesir": ["Altıeylül", "Ayvalık", "Balya", "Bandırma", "Bigadiç", "Burhaniye", "Dursunbey", "Edremit", "Erdek", "Gömeç", "Gönen", "Havran", "İvrindi", "Karesi", "Kepsut", "Manyas", "Marmara", "Savaştepe", "Sındırgı", "Susurluk"],
    "Bartın": ["Amasra", "Kurucaşile", "Merkez", "Ulus"],
    "Batman": ["Beşiri", "Gercüş", "Hasankeyf", "Kozluk", "Merkez", "Sason"],
    "Bayburt": ["Aydıntepe", "Demirözü", "Merkez"],
    "Bilecik": ["Bozüyük", "Gölpazarı", "İnhisar", "Merkez", "Osmaneli", "Pazaryeri", "Söğüt", "Yenipazar"],
    "Bingöl": ["Adaklı", "Genç", "Karlıova", "Kiğı", "Merkez", "Solhan", "Yayladere", "Yedisu"],
    "Bitlis": ["Adilcevaz", "Ahlat", "Güroymak", "Hizan", "Merkez", "Mutki", "Tatvan"],
    "Bolu": ["Dörtdivan", "Gerede", "Göynük", "Kıbrıscık", "Mengen", "Merkez", "Mudurnu", "Seben", "Yeniçağa"],
    "Burdur": ["Ağlasun", "Altınyayla", "Bucak", "Çavdır", "Çeltikçi", "Gölhisar", "Karamanlı", "Kemer", "Merkez", "Tefenni", "Yeşilova"],
    "Bursa": ["Büyükorhan", "Gemlik", "Gürsu", "Harmancık", "İnegöl", "İznik", "Karacabey", "Keles", "Kestel", "Mudanya", "Mustafakemalpaşa", "Nilüfer", "Orhaneli", "Orhangazi", "Osmangazi", "Yenişehir", "Yıldırım"],
    "Çanakkale": ["Ayvacık", "Bayramiç", "Biga", "Bozcaada", "Çan", "Eceabat", "Ezine", "Gelibolu", "Gökçeada", "Lapseki", "Merkez", "Yenice"],
    "Çankırı": ["Atkaracalar", "Bayramören", "Çerkeş", "Eldivan", "Ilgaz", "Kızılırmak", "Korgun", "Kurşunlu", "Merkez", "Orta", "Şabanözü", "Yapraklı"],
    "Çorum": ["Alaca", "Bayat", "Boğazkale", "Dodurga", "İskilip", "Kargı", "Laçin", "Mecitözü", "Merkez", "Oğuzlar", "Ortaköy", "Osmancık", "Sungurlu", "Uğurludağ"],
    "Denizli": ["Acıpayam", "Babadağ", "Baklan", "Bekilli", "Beyağaç", "Bozkurt", "Buldan", "Çal", "Çameli", "Çardak", "Çivril", "Güney", "Honaz", "Kale", "Merkezefendi", "Pamukkale", "Sarayköy", "Serinhisar", "Tavas"],
    "Diyarbakır": ["Bağlar", "Bismil", "Çermik", "Çınar", "Çüngüş", "Dicle", "Eğil", "Ergani", "Hani", "Hazro", "Kayapınar", "Kocaköy", "Kulp", "Lice", "Silvan", "Sur", "Yenişehir"],
    "Düzce": ["Akçakoca", "Cumayeri", "Çilimli", "Gölyaka", "Gümüşova", "Kaynaşlı", "Merkez", "Yığılca"],
    "Edirne": ["Enez", "Havsa", "İpsala", "Keşan", "Lalapaşa", "Meriç", "Merkez", "Süloğlu", "Uzunköprü"],
    "Elazığ": ["Ağın", "Alacakaya", "Arıcak", "Baskil", "Karakoçan", "Keban", "Kovancılar", "Maden", "Merkez", "Palu", "Sivrice"],
    "Erzincan": ["Çayırlı", "İliç", "Kemah", "Kemaliye", "Merkez", "Otlukbeli", "Refahiye", "Tercan", "Üzümlü"],
    "Erzurum": ["Aşkale", "Aziziye", "Çat", "Hınıs", "Horasan", "İspir", "Karaçoban", "Karayazı", "Köprüköy", "Narman", "Oltu", "Olur", "Palandöken", "Pasinler", "Pazaryolu", "Şenkaya", "Tekman", "Tortum", "Uzundere", "Yakutiye"],
    "Eskişehir": ["Alpu", "Beylikova", "Çifteler", "Günyüzü", "Han", "İnönü", "Mahmudiye", "Mihalgazi", "Mihalıççık", "Odunpazarı", "Seyitgazi", "Sivrihisar", "Tepebaşı"],
    "Gaziantep": ["Araban", "İslahiye", "Karkamış", "Nizip", "Nurdağı", "Oğuzeli", "Şahinbey", "Şehitkamil", "Yavuzeli"],
    "Giresun": ["Alucra", "Bulancak", "Çamoluk", "Çanakçı", "Dereli", "Doğankent", "Espiye", "Eynesil", "Görele", "Güce", "Keşap", "Merkez", "Piraziz", "Şebinkarahisar", "Tirebolu", "Yağlıdere"],
    "Gümüşhane": ["Kelkit", "Köse", "Kürtün", "Merkez", "Şiran", "Torul"],
    "Hakkari": ["Çukurca", "Derecik", "Merkez", "Şemdinli", "Yüksekova"],
    "Hatay": ["Altınözü", "Antakya", "Arsuz", "Belen", "Defne", "Dörtyol", "Erzin", "Hassa", "İskenderun", "Kırıkhan", "Kumlu", "Payas", "Reyhanlı", "Samandağ", "Yayladağı"],
    "Iğdır": ["Aralık", "Karakoyunlu", "Merkez", "Tuzluca"],
    "Isparta": ["Aksu", "Atabey", "Eğirdir", "Gelendost", "Gönen", "Keçiborlu", "Merkez", "Senirkent", "Sütçüler", "Şarkikaraağaç", "Uluborlu", "Yalvaç", "Yenişarbademli"],
    "İstanbul": ["Adalar", "Arnavutköy", "Ataşehir", "Avcılar", "Bağcılar", "Bahçelievler", "Bakırköy", "Başakşehir", "Bayrampaşa", "Beşiktaş", "Beykoz", "Beylikdüzü", "Beyoğlu", "Büyükçekmece", "Çatalca", "Çekmeköy", "Esenler", "Esenyurt", "Eyüpsultan", "Fatih", "Gaziosmanpaşa", "Güngören", "Kadıköy", "Kağıthane", "Kartal", "Küçükçekmece", "Maltepe", "Pendik", "Sancaktepe", "Sarıyer", "Silivri", "Sultanbeyli", "Sultangazi", "Şile", "Şişli", "Tuzla", "Ümraniye", "Üsküdar", "Zeytinburnu"],
    "İzmir": ["Aliağa", "Balçova", "Bayındır", "Bayraklı", "Bergama", "Beydağ", "Bornova", "Buca", "Çeşme", "Çiğli", "Dikili", "Foça", "Gaziemir", "Güzelbahçe", "Karabağlar", "Karaburun", "Karşıyaka", "Kemalpaşa", "Kınık", "Kiraz", "Konak", "Menderes", "Menemen", "Narlıdere", "Ödemiş", "Seferihisar", "Selçuk", "Tire", "Torbalı", "Urla"],
    "Kahramanmaraş": ["Afşin", "Andırın", "Çağlayancerit", "Dulkadiroğlu", "Ekinözü", "Elbistan", "Göksun", "Nurhak", "Onikişubat", "Pazarcık", "Türkoğlu"],
    "Karabük": ["Eflani", "Eskipazar", "Merkez", "Ovacık", "Safranbolu", "Yenice"],
    "Karaman": ["Ayrancı", "Başyayla", "Ermenek", "Kazımkarabekir", "Merkez", "Sarıveliler"],
    "Kars": ["Akyaka", "Arpaçay", "Digor", "Kağızman", "Merkez", "Sarıkamış", "Selim", "Susuz"],
    "Kastamonu": ["Abana", "Ağlı", "Araç", "Bozkurt", "Cide", "Çatalzeytin", "Daday", "Devrekani", "Doğanyurt", "Hanönü", "İhsangazi", "İnebolu", "Küre", "Merkez", "Pınarbaşı", "Seydiler", "Şenpazar", "Taşköprü", "Tosya"],
    "Kayseri": ["Akkışla", "Bünyan", "Develi", "Felahiye", "Hacılar", "İncesu", "Kocasinan", "Melikgazi", "Özvatan", "Pınarbaşı", "Sarıoğlan", "Sarız", "Talas", "Tomarza", "Yahyalı", "Yeşilhisar"],
    "Kilis": ["Elbeyli", "Merkez", "Musabeyli", "Polateli"],
    "Kırıkkale": ["Bahşılı", "Balışeyh", "Çelebi", "Delice", "Karakeçili", "Keskin", "Merkez", "Sulakyurt", "Yahşihan"],
    "Kırklareli": ["Babaeski", "Demirköy", "Kofçaz", "Lüleburgaz", "Merkez", "Pehlivanköy", "Pınarhisar", "Vize"],
    "Kırşehir": ["Akçakent", "Akpınar", "Boztepe", "Çiçekdağı", "Kaman", "Merkez", "Mucur"],
    "Kocaeli": ["Başiskele", "Çayırova", "Darıca", "Derince", "Dilovası", "Gebze", "Gölcük", "İzmit", "Kandıra", "Karamürsel", "Kartepe", "Körfez"],
    "Konya": ["Ahırlı", "Akören", "Akşehir", "Altınekin", "Beyşehir", "Bozkır", "Cihanbeyli", "Çeltik", "Çumra", "Derbent", "Derebucak", "Doğanhisar", "Emirgazi", "Ereğli", "Güneysınır", "Hadim", "Halkapınar", "Hüyük", "Ilgın", "Kadınhanı", "Karapınar", "Karatay", "Kulu", "Meram", "Sarayönü", "Selçuklu", "Seydişehir", "Taşkent", "Tuzlukçu", "Yalıhüyük", "Yunak"],
    "Kütahya": ["Altıntaş", "Aslanapa", "Çavdarhisar", "Domaniç", "Dumlupınar", "Emet", "Gediz", "Hisarcık", "Merkez", "Pazarlar", "Şaphane", "Simav", "Tavşanlı"],
    "Malatya": ["Akçadağ", "Arapgir", "Arguvan", "Battalgazi", "Darende", "Doğanşehir", "Doğanyol", "Hekimhan", "Kale", "Kuluncak", "Pütürge", "Yazıhan", "Yeşilyurt"],
    "Manisa": ["Ahmetli", "Akhisar", "Alaşehir", "Demirci", "Gölmarmara", "Gördes", "Kırkağaç", "Köprübaşı", "Kula", "Salihli", "Sarıgöl", "Saruhanlı", "Selendi", "Soma", "Şehzadeler", "Turgutlu", "Yunusemre"],
    "Mardin": ["Artuklu", "Dargeçit", "Derik", "Kızıltepe", "Mazıdağı", "Midyat", "Nusaybin", "Ömerli", "Savur", "Yeşilli"],
    "Mersin": ["Akdeniz", "Anamur", "Aydıncık", "Bozyazı", "Çamlıyayla", "Erdemli", "Gülnar", "Mezitli", "Mut", "Silifke", "Tarsus", "Toroslar", "Yenişehir"],
    "Muğla": ["Bodrum", "Dalaman", "Datça", "Fethiye", "Kavaklıdere", "Köyceğiz", "Marmaris", "Menteşe", "Milas", "Ortaca", "Seydikemer", "Ula", "Yatağan"],
    "Muş": ["Bulanık", "Hasköy", "Korkut", "Malazgirt", "Merkez", "Varto"],
    "Nevşehir": ["Acıgöl", "Avanos", "Derinkuyu", "Gülşehir", "Hacıbektaş", "Kozaklı", "Merkez", "Ürgüp"],
    "Niğde": ["Altunhisar", "Bor", "Çamardı", "Çiftlik", "Merkez", "Ulukışla"],
    "Ordu": ["Akkuş", "Altınordu", "Aybastı", "Çamaş", "Çatalpınar", "Çaybaşı", "Fatsa", "Gölköy", "Gülyalı", "Gürgentepe", "İkizce", "Kabadüz", "Kabataş", "Korgan", "Kumru", "Mesudiye", "Perşembe", "Ulubey", "Ünye"],
    "Osmaniye": ["Bahçe", "Düziçi", "Hasanbeyli", "Kadirli", "Merkez", "Sumbas", "Toprakkale"],
    "Rize": ["Ardeşen", "Çamlıhemşin", "Çayeli", "Derepazarı", "Fındıklı", "Güneysu", "Hemşin", "İkizdere", "İyidere", "Kalkandere", "Merkez", "Pazar"],
    "Sakarya": ["Adapazarı", "Akyazı", "Arifiye", "Erenler", "Ferizli", "Geyve", "Hendek", "Karapürçek", "Karasu", "Kaynarca", "Kocaali", "Pamukova", "Sapanca", "Serdivan", "Söğütlü", "Taraklı"],
    "Samsun": ["19 Mayıs", "Alaçam", "Asarcık", "Atakum", "Ayvacık", "Bafra", "Canik", "Çarşamba", "Havza", "İlkadım", "Kavak", "Ladik", "Salıpazarı", "Tekkeköy", "Terme", "Vezirköprü", "Yakakent"],
    "Siirt": ["Baykan", "Eruh", "Kurtalan", "Merkez", "Pervari", "Şirvan", "Tillo"],
    "Sinop": ["Ayancık", "Boyabat", "Dikmen", "Durağan", "Erfelek", "Gerze", "Merkez", "Saraydüzü", "Türkeli"],
    "Sivas": ["Akıncılar", "Altınyayla", "Divriği", "Doğanşar", "Gemerek", "Gölova", "Gürün", "Hafik", "İmranlı", "Kangal", "Koyulhisar", "Merkez", "Suşehri", "Şarkışla", "Ulaş", "Yıldızeli", "Zara"],
    "Şanlıurfa": ["Akçakale", "Birecik", "Bozova", "Ceylanpınar", "Eyyübiye", "Halfeti", "Haliliye", "Harran", "Hilvan", "Karaköprü", "Siverek", "Suruç", "Viranşehir"],
    "Şırnak": ["Beytüşşebap", "Cizre", "Güçlükonak", "İdil", "Merkez", "Silopi", "Uludere"],
    "Tekirdağ": ["Çerkezköy", "Çorlu", "Ergene", "Hayrabolu", "Kapaklı", "Malkara", "Marmaraereğlisi", "Muratlı", "Saray", "Süleymanpaşa", "Şarköy"],
    "Tokat": ["Almus", "Artova", "Başçiftlik", "Erbaa", "Merkez", "Niksar", "Pazar", "Reşadiye", "Sulusaray", "Turhal", "Yeşilyurt", "Zile"],
    "Trabzon": ["Akçaabat", "Araklı", "Arsin", "Beşikdüzü", "Çarşıbaşı", "Çaykara", "Dernekpazarı", "Düzköy", "Hayrat", "Köprübaşı", "Maçka", "Of", "Ortahisar", "Sürmene", "Şalpazarı", "Tonya", "Vakfıkebir", "Yomra"],
    "Tunceli": ["Çemişgezek", "Hozat", "Mazgirt", "Merkez", "Nazımiye", "Ovacık", "Pertek", "Pülümür"],
    "Uşak": ["Banaz", "Eşme", "Karahallı", "Merkez", "Sivaslı", "Ulubey"],
    "Van": ["Bahçesaray", "Başkale", "Çaldıran", "Çatak", "Edremit", "Erciş", "Gevaş", "Gürpınar", "İpekyolu", "Muradiye", "Özalp", "Saray", "Tuşba"],
    "Yalova": ["Altınova", "Armutlu", "Çınarcık", "Çiftlikköy", "Merkez", "Termal"],
    "Yozgat": ["Akdağmadeni", "Aydıncık", "Boğazlıyan", "Çandır", "Çayıralan", "Çekerek", "Kadışehri", "Saraykent", "Sarıkaya", "Sorgun", "Şefaatli", "Yenifakılı", "Yerköy", "Merkez"],
    "Zonguldak": ["Alaplı", "Çaycuma", "Devrek", "Gökçebey", "Karadeniz Ereğli", "Kilimli", "Kozlu", "Merkez"]
}

# ================= 1. KULLANICININ PORTFÖY LİSTESİ =================
@router.get("/my", response_class=HTMLResponse)
def get_my_portfolios(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        res = (
            supabase.table("portfolios")
            .select("*")
            .eq("porfoy_sahibi_id", clean_user_id)
            .order("created_at", desc=True)
            .execute()
        )
        portfolios = res.data or []
    except Exception as e:
        portfolios = []
        print(f"Portföyleri getirme hatası: {e}")

    return templates.TemplateResponse(
        request=request,
        name="portfolios/list.html",
        context={"portfolios": portfolios}
    )

# ================= 2. PORTFÖY EKLEME (ORTAK SATIŞ PRENSİBİ & GÖRÜNÜRLÜK) =================
@router.get("/add", response_class=HTMLResponse)
def get_add_portfolio(request: Request, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request, 
        name="portfolios/add.html",
        context={"turkey_data": TURKEY_DISTRICTS}
    )

@router.post("/add")
async def post_add_portfolio(
    request: Request,
    il: str = Form(...),
    ilce: str = Form(...),
    mahalle: str = Form(None),
    gayrimenkul_tipi: str = Form(...),
    fiyat: int = Form(...),
    oda: str = Form(None),
    m2: int = Form(None),
    kisa_aciklama: str = Form(None),
    yetki_durumu: str = Form("Satış Yetkili"),
    visibility: str = Form("network"), # network, group, private
    fotograflar: List[UploadFile] = File([]),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    uploaded_urls = []

    if fotograflar:
        for f in fotograflar:
            if f.filename:
                try:
                    file_bytes = await f.read()
                    if len(file_bytes) > 0:
                        ext = f.filename.split(".")[-1].lower() if "." in f.filename else "jpg"
                        file_name = f"{uuid.uuid4()}.{ext}"

                        supabase.storage.from_("portfolios").upload(
                            path=file_name,
                            file=file_bytes,
                            file_options={"content-type": f.content_type or f"image/{ext}"}
                        )

                        public_url = supabase.storage.from_("portfolios").get_public_url(file_name)
                        uploaded_urls.append(public_url)
                except Exception as upload_err:
                    print(f"[STORAGE YÜKLEME HATASI]: {upload_err}")

    ana_foto = uploaded_urls[0] if uploaded_urls else "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=600&q=80"

    try:
        data = {
            "porfoy_sahibi_id": clean_user_id,
            "il": il.strip(),
            "ilce": ilce.strip(),
            "mahalle_site": mahalle.strip() if mahalle else None,
            "gayrimenkul_tipi": gayrimenkul_tipi,
            "fiyat": int(fiyat) if fiyat else None,
            "oda": oda,
            "m2": int(m2) if m2 else None,
            "kisa_aciklama": kisa_aciklama,
            "ana_fotograf": ana_foto,
            "fotograflar": uploaded_urls,
            "yetki_durumu": yetki_durumu,
            "visibility": visibility,  # network, group, private
            "isbirliğine_acik": True,
            "durum": "Aktif"
        }
        res = supabase.table("portfolios").insert(data).execute()
        portfolio_id = res.data[0]["id"] if res.data else None

        return RedirectResponse(
            url=f"/portfolios/agents-for/{portfolio_id}",
            status_code=303
        )
    except Exception as e:
        print(f"Portföy kayıt hatası: {e}")
        return templates.TemplateResponse(
            request=request,
            name="portfolios/add.html",
            context={"message": f"Hata: {str(e)}", "turkey_data": TURKEY_DISTRICTS}
        )

# ================= 3. UYGUN EMLAKÇILARI GETİR (DİNAMİK KRİTER & GÖRÜNÜRLÜK KORUMALI) =================
@router.get("/agents-for/{portfolio_id}", response_class=HTMLResponse)
def get_matching_agents(
    request: Request,
    portfolio_id: str,
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        # 1. Portföy Bilgisini Çek
        p_res = (
            supabase.table("portfolios")
            .select("*")
            .eq("id", portfolio_id)
            .single()
            .execute()
        )
        portfolio = p_res.data or {}
        if not portfolio:
            return RedirectResponse(url="/portfolios/my", status_code=303)

        port_ilce = str(portfolio.get("ilce") or "").strip().lower()
        port_mahalle = str(portfolio.get("mahalle_site") or "").strip().lower()
        port_price = int(portfolio.get("fiyat") or 0)
        port_oda_str = str(portfolio.get("oda") or "").strip().lower()
        
        raw_port_features = str(portfolio.get("kisa_aciklama") or "")
        port_features_set = {
            f.strip().lower() 
            for f in raw_port_features.replace("✓", "").replace("+", "").split(",") 
            if f.strip()
        }

        def parse_room_count(val_str: str) -> int:
            try:
                parts = val_str.replace(" ", "").split("+")
                return int(parts[0])
            except Exception:
                return 0

        port_rooms = parse_room_count(port_oda_str)

        # Portföy sahibinin üye olduğu grup kimlikleri (Group görünürlük denetimi için)
        my_gm = supabase.table("group_members").select("group_id").eq("user_id", clean_user_id).execute()
        my_group_ids = {str(item["group_id"]) for item in (my_gm.data or []) if item.get("group_id")}

        # 2. Aktif Meslektaşları Al
        u_res = (
            supabase.table("users")
            .select("id, ad_soyad, eposta, telefon, sirket_unvani, profil_foto, calistigi_ilceler, uzmanlik_alanlari")
            .neq("id", clean_user_id)
            .eq("durum", "aktif")
            .execute()
        )
        all_agents = u_res.data or []

        # 3. İlgili İlçedeki Talepleri Çek (Private OLANLAR HARİÇ)
        d_res = (
            supabase.table("buyer_demands")
            .select("*")
            .eq("durum", "Aktif")
            .neq("visibility", "private") # Gizli alıcı talepleri eşleşmeye dahil edilmez
            .ilike("ilce", f"%{port_ilce}%")
            .execute()
        )
        demands = d_res.data or []

        # Danışmanların taleplerini eşleştir (Group görünürlüğü kuralı ile)
        user_demands_map = {}
        for d in demands:
            uid = str(d.get("user_id")).strip()
            d_vis = str(d.get("visibility") or "network").lower()

            # Eğer talep 'group' ise ortak grup şartı aranır
            if d_vis == "group":
                try:
                    d_owner_gm = supabase.table("group_members").select("group_id").eq("user_id", uid).execute()
                    d_owner_groups = {str(item["group_id"]) for item in (d_owner_gm.data or []) if item.get("group_id")}
                    if not my_group_ids.intersection(d_owner_groups):
                        continue # Ortak grup yoksa bu talep elenir
                except Exception:
                    continue

            if uid not in user_demands_map:
                user_demands_map[uid] = []
            user_demands_map[uid].append(d)

        scored_agents = []

        for agent in all_agents:
            agent_id = str(agent.get("id")).strip()

            if is_relationship_blocked(clean_user_id, agent_id):
                continue

            raw_districts = agent.get("calistigi_ilceler") or []
            agent_districts = [str(x).strip().lower() for x in (raw_districts if isinstance(raw_districts, list) else raw_districts.split(","))]
            
            agent_demands = user_demands_map.get(agent_id, [])
            works_in_district = (port_ilce in agent_districts) or any(port_ilce in d or d in port_ilce for d in agent_districts)

            if not works_in_district and not agent_demands:
                continue

            best_score = 0
            best_demand_text = "Bölgede aktif danışman"

            if agent_demands:
                for dem in agent_demands:
                    current_base_score = 0

                    # A. Lokasyon (30 / 20)
                    dem_mahalle = str(dem.get("mahalle_site") or "").strip().lower()
                    if port_mahalle and dem_mahalle and (port_mahalle in dem_mahalle or dem_mahalle in port_mahalle):
                        current_base_score += 30
                    else:
                        current_base_score += 20

                    # B. Oda Sayısı (10)
                    dem_oda_str = str(dem.get("oda_sayisi") or "").strip().lower()
                    dem_rooms = parse_room_count(dem_oda_str)
                    if dem_rooms > 0:
                        if port_rooms >= dem_rooms:
                            current_base_score += 10
                    else:
                        current_base_score += 5

                    # C. Bütçe (10)
                    min_b = int(dem.get("min_butce") or 0)
                    max_b = int(dem.get("max_butce") or 0)
                    if port_price > 0:
                        if min_b > 0 and max_b > 0:
                            if min_b <= port_price <= max_b:
                                current_base_score += 10
                            elif port_price <= (max_b * 1.1):
                                current_base_score += 5
                        elif max_b > 0:
                            if port_price <= max_b:
                                current_base_score += 10
                            elif port_price <= (max_b * 1.1):
                                current_base_score += 5
                        else:
                            current_base_score += 10
                    else:
                        current_base_score += 5

                    # D. 40 Nitelik & Donatı Dağılımı
                    raw_dem_features = dem.get("ozellikler") or []
                    if isinstance(raw_dem_features, str):
                        dem_features_list = [f.strip().lower() for f in raw_dem_features.split(",") if f.strip()]
                    else:
                        dem_features_list = [str(f).strip().lower() for f in raw_dem_features if f]

                    total_dem_features_count = len(dem_features_list)
                    feature_bonus_score = 0

                    if total_dem_features_count > 0:
                        remaining_pool = max(0, 100 - current_base_score)
                        per_feature_weight = remaining_pool / total_dem_features_count

                        matched_features_count = 0
                        for f in dem_features_list:
                            if any(f in pf or pf in f for pf in port_features_set):
                                matched_features_count += 1

                        feature_bonus_score = round(matched_features_count * per_feature_weight)

                    total_calculated_score = current_base_score + feature_bonus_score
                    final_score = min(total_calculated_score, 100)

                    if final_score > best_score:
                        best_score = final_score
                        b_max = round(max_b / 1_000_000, 1) if max_b > 0 else 0
                        best_demand_text = f"{b_max:g}M TL bütçeli hazır alıcısı ile %{final_score} uyumlu" if b_max > 0 else f"Hazır alıcısı ile %{final_score} kriter uyumu"

            else:
                best_score = 50
                best_demand_text = f"{portfolio.get('ilce', 'Bölge')} uzmanı danışman"

            agent["match_score"] = best_score
            agent["buyer_pool_text"] = best_demand_text
            scored_agents.append(agent)

        scored_agents.sort(key=lambda x: x["match_score"], reverse=True)

    except Exception as e:
        portfolio = {}
        scored_agents = []
        print(f"[DİNAMİK KRİTER SKORLAMA HATASI]: {e}")

    return templates.TemplateResponse(
        request=request,
        name="portfolios/matching_agents.html",
        context={"portfolio": portfolio, "agents": scored_agents}
    )


# ================= 4. ORTAK SATIŞ TALEBİ GÖNDER (KOMİSYONSUZ) =================
@router.post("/send-referral")
def post_send_referral(
    request: Request,
    portfolio_id: str = Form(...),
    agent_id: str = Form(...),
    agent_name: str = Form(...),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_target_id = str(agent_id).strip()

    try:
        ins_res = supabase.table("collaboration_requests").insert({
            "talep_gonderen_id": clean_user_id,
            "talep_alan_id": clean_target_id,
            "ilgili_ilan_id": portfolio_id,
            "talep_tipi": "Ortak Satış Talebi",
            "isbirligi_kosulu": "Ortak Satış (Hizmet Bedeli Taraflarca Alınır)",
            "durum": "Beklemede"
        }).execute()
        print(f"[ORTAK SATIŞ OLUŞTURULDU]: {ins_res.data}")

        sender = supabase.table("users").select("ad_soyad").eq("id", clean_user_id).single().execute()
        s_name = sender.data.get("ad_soyad") if sender.data else "Bir meslektaşınız"
        send_notification(
            user_id=clean_target_id,
            baslik="Yeni Ortak Satış Talebi 🏡",
            icerik=f"{s_name} yetkili mülkünü sizinle ortak satış modeliyle pazarlamak istiyor.",
            hedef_url="/collaborations/my?tab=bekleyen"
        )

        p_res = (
            supabase.table("portfolios")
            .select("*")
            .eq("id", portfolio_id)
            .single()
            .execute()
        )
        portfolio = p_res.data or {}
    except Exception as e:
        portfolio = {}
        print(f"Ortak satış talebi hatası: {e}")

    return templates.TemplateResponse(
        request=request,
        name="portfolios/success.html",
        context={"portfolio": portfolio, "agent_name": agent_name}
    )

# ================= 5. SİLME =================
@router.post("/delete/{portfolio_id}")
def post_delete_portfolio(portfolio_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()
    clean_port_id = str(portfolio_id).strip()

    try:
        chk = (
            supabase.table("portfolios")
            .select("id, porfoy_sahibi_id")
            .eq("id", clean_port_id)
            .execute()
        )
        
        if not chk.data or len(chk.data) == 0:
            return RedirectResponse(url="/portfolios/my", status_code=303)

        owner_id = str(chk.data[0].get("porfoy_sahibi_id") or "").strip()
        if owner_id != clean_user_id:
            return RedirectResponse(url="/portfolios/my", status_code=303)

        supabase.table("portfolios").delete().eq("id", clean_port_id).execute()
    except Exception as e:
        print(f"[PORTFÖY SİLME KRİTİK HATA]: {e}\n")

    return RedirectResponse(url="/portfolios/my", status_code=303)

# ================= 6. DURUM DEĞİŞTİRME =================
@router.post("/toggle-status/{portfolio_id}")
def post_toggle_status(portfolio_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        p = supabase.table("portfolios").select("id, durum").eq("id", portfolio_id).eq("porfoy_sahibi_id", clean_user_id).single().execute()
        if p.data:
            current_st = str(p.data.get("durum") or "").strip().lower()
            
            if current_st == "satıldı":
                return RedirectResponse(url="/portfolios/my?error=locked", status_code=303)

            new_st = "Pasif" if current_st == "aktif" else "Aktif"
            supabase.table("portfolios").update({"durum": new_st}).eq("id", portfolio_id).execute()
    except Exception as e:
        print(f"Durum değiştirme hatası: {e}")

    return RedirectResponse(url="/portfolios/my", status_code=303)

# ================= 7. DÜZENLEME =================
@router.get("/edit/{portfolio_id}", response_class=HTMLResponse)
def get_edit_portfolio(request: Request, portfolio_id: str, user_id: str = Cookie(None)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        res = supabase.table("portfolios").select("*").eq("id", portfolio_id).eq("porfoy_sahibi_id", clean_user_id).single().execute()
        portfolio = res.data
        if not portfolio:
            return RedirectResponse(url="/portfolios/my", status_code=303)
            
        if str(portfolio.get("durum")).strip().lower() == "satıldı":
            return RedirectResponse(url="/portfolios/my?error=locked", status_code=303)
    except Exception as e:
        return RedirectResponse(url="/portfolios/my", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="portfolios/edit.html",
        context={"portfolio": portfolio}
    )

@router.post("/edit/{portfolio_id}")
def post_edit_portfolio(
    request: Request,
    portfolio_id: str,
    fiyat: int = Form(...),
    oda: str = Form(None),
    m2: int = Form(None),
    kisa_aciklama: str = Form(None),
    durum: str = Form("Aktif"),
    user_id: str = Cookie(None)
):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    clean_user_id = str(user_id).strip()

    try:
        p_chk = supabase.table("portfolios").select("durum").eq("id", portfolio_id).single().execute()
        final_status = durum
        if p_chk.data and str(p_chk.data.get("durum")).strip().lower() == "satıldı":
            final_status = "Satıldı"

        supabase.table("portfolios").update({
            "fiyat": int(fiyat) if fiyat else None,
            "oda": oda,
            "m2": int(m2) if m2 else None,
            "kisa_aciklama": kisa_aciklama,
            "durum": final_status
        }).eq("id", portfolio_id).eq("porfoy_sahibi_id", clean_user_id).execute()
    except Exception as e:
        print(f"Güncelleme hatası: {e}")
    return RedirectResponse(url="/portfolios/my", status_code=303)