# chimera-convert

Muuntaa lauluäänitteen (wav, mp3, flac …) ja sen sanoituksen CHIMERAn melodiatiedostoksi, jonka
`chimera render notes` laulaa.

```
äänite ─► [Demucs: laulu erilleen] ─► sävelkorkeus (torchcrepe) ─► nuotit (viritystä seuraava HMM) ─┐
                                    └► sanoituksen kohdistus (MMS, vain laulettuihin kohtiin) ─────┤
sanoitus ─► sanat ─► tavut (suomi: säännöt, englanti: Chimeran oma jako) ───────────────────────────┴► tavut nuoteille ─► .json
```

1. **Laulu erilleen** (oletuksena päällä, `--separate`): Demucs htdemucs erottaa lauluraidan
   taustoista. Ilman sitä sävelkäyrä lasketaan koko miksauksesta ja tulos on selvästi huonompi.
2. **Sävelkorkeus** 10 ms välein: torchcrepe näytönohjaimella (varalla librosan pYIN).
3. **Nuotit ennen sanoja** (`transcribe.py`): laulajan viritys seurataan liukuvasti (vibrato
   keskiarvoistetaan pois), joten laulaja, joka valuu kappaleen aikana 40 senttiä alas, pysyy
   samoilla nuoteilla. Nuotit löydetään piilo-Markov-mallilla (tila jokaiselle puolisävelelle ja
   hiljaisuudelle): nuotti pysyy vibraton ja lyhyiden konsonanttikatkojen yli, eikä liukuma tai
   heitto muutu omaksi nuotikseen. Toistettu sama sävel jaetaan katkon tai voimakkuuden notkahduksen
   kohdalta.
4. **Tavut**: suomi tavutetaan oikeinkirjoitussäännöillä, englanti **Chimeran omalla jaolla**.
5. **Kohdistus**: monikielinen MMS-kohdistusmalli kertoo suunnilleen, milloin kunkin tavun vokaali
   alkaa. Vokaalit sallitaan vain kohtiin, joissa lauletaan, joten kohdistus ei karkaa soolo-osiin.
6. **Tavut nuoteille** (`assign.py`): koko kappale ratkaistaan kerralla dynaamisella ohjelmoinnilla.
   Tavu alkaa nuotin alusta (tai saman sävelen jakokohdasta), mahdollisimman lähellä mallin aikaa;
   tavun ja seuraavan välissä olevat nuotit ovat melismaa; hengityksen jälkeinen laulu, jota mikään
   tavu ei tarvitse (taustalaulu, huudahdukset), jätetään pois; rivinvaihto suosii hengitystä.
   Tavu, jolle ei löydy laulua, merkitään editorissa tarkistettavaksi.

Tulos käyttää tempoa 60 bpm, jolloin yksi isku on yksi sekunti ja nuottien kestot ovat suoraan
äänitteen ajoitus.

**Kieli** luetaan sanoituksesta (suomi tai englanti). Jos sanoista ei voi päätellä kieltä
varmasti (liian vähän sanoja, molempia kieliä, tai sanat näyttävät muulta kieleltä kuten
ruotsilta), muunnin kysyy sitä: sovellus näyttää kielivalinnan, ja komentorivi pysähtyy ja pyytää
`--lang fi` tai `--lang en`. Kielen voi aina valita myös itse.

## Sovellus

`scripts\start_app.bat` käynnistää muuntimen sovelluksen osoitteeseen http://127.0.0.1:5320 ja
avaa sen selaimeen. Sulje ikkuna lopettaaksesi.

Käyttöliittymä on englanniksi.

1. **New song**: pudota äänite, kirjoita sanat. Kieli tunnistetaan kirjoittaessa (Language:
   Detect); jos se ei ole varma, valitse Finnish tai English ennen muuntamista. Valitse
   "Separate the voice", jos äänite on valmis kappale taustoineen.
2. **Muunnos** etenee palkissa (ensimmäinen kerta lataa mallit). Ensin ääni analysoidaan
   (erotus, sävelkorkeus, sanojen kohdistusmalli), sitten pysähdytään vaiheeseen **What counts as
   singing**: kuvassa laulun voimakkuus ja sävelen selkeys koko kappaleen ajalta, ja vihreä nauha
   näyttää, mikä lasketaan lauluksi (harmaa = kova mutta ei laskettu). Klikkaa kuvaa kuunnellaksesi
   kohdan. Säädä tarvittaessa:
   - *Level threshold*: laulu on tätä kovempaa (dB kovimmasta). Laske, jos hiljaista laulua jää pois.
   - *Pitch clarity needed*: kuinka selvä sävelen pitää olla. Laske henkäilevälle tai kaikuiselle laululle.
   - *Rough voice counts*: kova laulu ilman selvää säveltä (huuto, räkä, särö) lasketaan lauluksi.
     Vain erotetulle laululle (tai pelkälle laulunauhalle); valmiissa miksauksessa pidä 0:ssa.
   - *Hold syllables over gaps*: tätä lyhyemmän katkon yli tavu pidetään soimassa (sanat eivät
     jää lyhyiksi), mutta rivin vaihdossa laulaja hengittää.
   **Make the notes →** tekee nuotit näillä (muutama sekunti, analyysiä ei tehdä uudelleen).
   Editorin **Singing…** palaa tähän vaiheeseen; **Back to the notes** palaa muuttamatta mitään.
   Jos haluat ohittaa vaiheen, poista uutta kappaletta lisätessä valinta "Let me check what counts
   as singing".
3. **Editori**: piano roll, jossa laulettu sävelkäyrä (oranssi), tavunuotit (sininen) ja melismat
   (pinkki). Vedä nuottia ylös/alas sävelen vaihtamiseksi ja reunoista ajoituksen muuttamiseksi,
   Shift+veto siirtää. Näppäimet: S jaa, Delete yhdistä edelliseen, [ ] siirrä tavu edelliseen tai
   seuraavaan nuottiin, ↑↓ sävel, välilyönti soittaa, Ctrl+Z kumoa. Kielen voi vaihtaa otsikon
   vierestä (Language; nuotit sijoitetaan silloin uudelleen). Oranssit katkoviivalliset nuotit
   ovat tavuja, joille ei löytynyt laulua: tilarivin "N to check ▸" hyppää seuraavaan.
4. **Open in Chimera (live)** avaa kappaleen Chimeran omaan Sing-tilaan (Chimeran pitää olla
   käynnissä: `start_chimera.bat`). Siellä kappale soi Chimeran moottorissa reaaliajassa, ja
   äänen säätimet toimivat soiton aikana: *Song*-sivun Vibrato, Rate, Breathy ja Ring, *Tone*-sivun
   Bright ja Transpose, Voice-paneelin Pressed, Rough ja Fry sekä yläpalkin ääni (Male/Female/Child,
   vaihto aloittaa kappaleen alusta). Vibrato ja Transpose vaikuttavat noin puolen sekunnin
   viiveellä, muut heti. Laulu alkaa heti (äänitteen intron hiljaisuus jätetään pois) ja jatkuu,
   vaikka ikkuna olisi taustalla.
5. **Sing with Chimera** renderöi nykyiset nuotit tiedostoksi; toiston lähde
   "Recording"/"Voice"/"Chimera" vaihtaa vertailtavaa.
6. **Duet show…** tekee show'n Chimeran duettisivulle (`public\shows\<tunnus>`, ei gitissä):
   avaa Chimera (`start_chimera.bat`) ja osoite `http://127.0.0.1:5317/?show=<tunnus>`.
   Show-sivulla on kaksi tilaa: **Recorded** soittaa valmiin renderöinnin, **Live voice** laulaa
   kappaleen Chimeran moottorilla sivulla itsessään taustan päälle (tausta = äänite ilman laulua,
   tehdään kun äänestä on erotettu laulu). **Voice settings** -paneelissa valitaan laulajan
   luonne (Natural, Soft, Pop, Rock, Opera, Crooner, Folk) ja keho (Male/Female/Child tai väliltä),
   ja säädetään vibrato, nopeus, transponointi, väljyys, kirkkaus, henkäisy, ring, puristus,
   karheus, fry, murina, voima sekä laulun ja taustan voimakkuus; kaikki kuuluvat heti.
   **+ Save voice** tallentaa oman äänen nimellä, ja show muistaa viimeksi käytetyn äänen.
   **Download melody** antaa `render notes` -tiedoston.

Kappaleet tallentuvat kansioon `out\sessions\` (ei gitissä). Käyttöliittymän lähdekoodi on
kansiossa `app\` (React + Vite, Chimeran tyylillä); `app\README.md` kertoo, miten sen voi kääntää
uudelleen.

## Siirto toiselle koneelle

Vanhalla koneella: kaksoisnapsauta Chimeran kansiossa `siirra_toiselle_koneelle.bat`. Se kysyy
kohteen (USB-tikku, verkkojako tai kansio) ja tekee sinne kansion `ChimeraSiirto`: Chimera kaikkine
paikallisine muutoksineen ja committeineen, valmiiksi käännetty moottori ja `chimera.exe`, muunnin
sovelluksineen sekä halutessa mallit (noin 1,3 Gt) ja omat kappaleet.

Uudella koneella: kaksoisnapsauta `ChimeraSiirto\ASENNA.bat`. Se asentaa puuttuvat ohjelmat
wingetillä (Python 3.12, Bun), tekee muuntimen Python-ympäristön (torch CUDA:lla, jos koneessa on
NVIDIA, muuten CPU-versio), asentaa Chimeran paketit ja tekee työpöydälle kuvakkeet "Chimera" ja
"Chimera-muunnin". Rustia ei tarvita, ellei moottoria aiota muokata (`ASENNA.bat -Dev`).

## Asennus (Windows, NVIDIA)

Python 3.12 (koneellasi asennettuna) tai 3.11; Demucsin riippuvuuksilla ei välttämättä ole vielä paketteja 3.13:lle.
Muunnin on Chimeran repossa kansiossa `tools\chimera-convert`.

```powershell
cd $env:USERPROFILE\chimera-vocal-synth\tools\chimera-convert
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

Sama onnistuu ajamalla `scripts\install.bat`, joka myös tarkistaa asennuksen ja ajaa testit.

Tarkista, että näytönohjain löytyy: `python -c "import torch; print(torch.cuda.is_available())"`.

Englantia varten Chimeran CLI käännetään kerran repon juuressa (sen tavujako luetaan siltä):

```powershell
cd $env:USERPROFILE\chimera-vocal-synth
cargo build --release -p chimera-cli
```

Ensimmäinen ajo lataa mallit: MMS-kohdistusmalli noin 1,2 Gt (Hugging Face) ja Demucs noin
80 Mt. Ne tallentuvat välimuistiin.

## Käyttö

Tallenna muunnokset kansioon `out\`: se on rajattu gitin ulkopuolelle (`.git\info\exclude`),
joten äänitteistä tehdyt tiedostot eivät päädy repoon.

```powershell
# a cappella tai valmiiksi erotettu lauluraita
python -m chimera_convert laulu.wav sanat.txt -o out\laulu.json

# valmis kappale taustoineen: laulu erotetaan ensin
python -m chimera_convert kappale.mp3 sanat.txt --separate --plot -o out\kappale.json

# englanti; Chimera löytyy oletuksena kotikansiosta (%USERPROFILE%\chimera-vocal-synth),
# muualta --chimera POLKU
python -m chimera_convert song.mp3 lyrics.txt --lang en --separate -o out\song.json   # kieli valittu itse
```

Sitten Chimerassa (repon juuressa):

```powershell
.\target\release\chimera.exe render notes tools\chimera-convert\out\song.json song-chimera female
```

### Tulosteet

| Tiedosto | Sisältö |
|---|---|
| `laulu.json` | Chimeran melodiatiedosto: `bpm`, `lyrics`, `notes: [[midi, iskuja], …]` (midi 0 on tauko), `t0`, `vibrato` sekä tiedoksi `source`, `lang`, `body` (Chimera ei lue näitä kolmea). |
| `laulu.csv` | Nuotit tarkistusta varten: alku, loppu, sävel, tavu. |
| `laulu.png` | (`--plot`) Laulettu sävelkäyrä, nuotit ja tavut samassa kuvassa. Nopein tapa nähdä, osuiko kohdistus. |
| `laulu.vocals.wav` | (`--separate`) Erotettu lauluraita. Kuuntele, jos tulos näyttää oudolta. |

### Valinnat

| Valinta | Oletus | Merkitys |
|---|---|---|
| `--lang auto\|fi\|en` | `auto` | sanoituksen kieli; `auto` lukee sen sanoista ja pysähtyy kysymään, jos se ei ole varma |
| `--separate` | pois | erota laulu taustoista ensin |
| `--align mms\|none` | `mms` | `none`: ei kohdistusta, tavut nuoteille järjestyksessä (kevyt, mutta virheherkkä) |
| `--pitch crepe\|pyin` | crepe | sävelkorkeuden seuranta |
| `--transpose N` | 0 | puolisävelaskelia, esim. `-12` naisen laulu miesäänelle |
| `--keep-cents` | pois | säilytä laulettu sävel sentin tarkkuudella pyöristämisen sijaan |
| `--min-note S` | 0,10 | lyhin sävel omana nuottinaan; lyhyemmät (liukumat, vibraton heitot) sulautetaan |
| `--rest S` | 0,25 | lyhin hiljaisuus, joka kirjoitetaan taukona |
| `--vibrato C` | 35 | tiedostoon kirjoitettava vibraton syvyys sentteinä |

## Sanoitustiedosto

- UTF-8-tekstiä. Rivinvaihto, pilkku ja piste merkitsevät hengitystä.
- Kirjoita sanat **täsmälleen niin kuin ne lauletaan**: kertosäkeen toistot auki, ei "×2"-merkintöjä,
  ei puhuttuja välihuutoja, joita äänitteessä ei ole.
- Suomen yhdyssanat tavutetaan säännöillä oikein vain, jos raja on merkitty: `kesä-yö`,
  `rakkaus-laulu`. Myös muun tavutuksen voi pakottaa tavuviivalla.
- Melismoja ei tarvitse merkitä; muunnin päättelee ne melodiasta.
- Yksi kieli per kappale. Jos sanoissa on sekä suomea että englantia, muunnin kysyy, kummalla
  kielellä kappale lauletaan (toisen kielen sanat lausutaan silloin valitun kielen säännöin).

## Rajoitukset

- Suomi soi `render notes` -komennolla, kun melodiatiedostossa on `"lang": "fi"` (muunnin kirjoittaa
  sen). Muunnin kirjoittaa suomen sanat valmiiksi tavutettuina (`kis-sa`) ja tarkistaa lopuksi
  tavumäärän Chimeralta. Duettisivu (`?show=`) lukee melodiatiedoston sanat vielä englannin
  säännöin, joten suomenkielisen show'n sanat suun vieressä voivat mennä väärin.
- Chimeran melismamerkki `-` toimii vain sanojen välissä. Sävelvaihdos sanan sisällä (muulla kuin
  viimeisellä tavulla) yhdistetään yhdeksi nuotiksi, jonka sävel on pidemmän osan sävel.
- Vain yksi laulaja kerrallaan. Taustalaulut, harmoniat ja voimakas kaiku tai autotune
  sekoittavat sävelkorkeuden seurantaa ja kohdistusta.
- Kohdistus olettaa, että sanoitus vastaa laulua. Puuttuva tai ylimääräinen säe siirtää kaikkia
  sen jälkeisiä tavuja.
- Englannissa tavumäärä on varma vain, kun Chimera löytyy (`--chimera`, ja sen
  `target\release\chimera.exe` on käännetty). Ilman sitä tuntemattomien sanojen tavut arvataan.
  Lopuksi muunnin tarkistaa tavumäärän Chimeralta ja varoittaa, jos se ei täsmää.
- Tekijänoikeuden alaisista äänitteistä tehtyjä tiedostoja ei pidä lisätä Chimeran git-repoon
  (repon sääntö). Pidä ne kansiossa `out\` tai repon ulkopuolella.

## Testit

```powershell
python -m pytest -q
```

Testit tarkistavat kielen tunnistuksen, suomen tavutuksen, Chimeran tavujaon lukemisen,
CTC-kohdistuksen, nuottien muodostuksen synteettisellä laulusignaalilla (sävelet, vibrato, legato,
tauko, melisma, sävelen ennakointi konsonantissa), koko ajon sekä sovelluksen palvelimen
(muunnos, muokkaus, renderöinti, show-vienti, kielen vaihto). Käyttöliittymän muokkaussäännöt
testataan `app`-kansiossa: `bun run test`.

`scripts\smoke.bat` ajaa oikeilla malleilla edestakaisen testin: Chimera laulaa demokappaleensa,
muunnin lukee ne takaisin ja Chimera laulaa tuloksen.
