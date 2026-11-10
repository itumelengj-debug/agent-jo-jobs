"""Where a role is open to, and whether that includes you.

A job's location field is three different things depending on the board: an
office ("Bangalore, India"), a list of places a remote worker may live
("LATAM, Canada, USA", "EMEA"), or nothing at all ("Remote"). The old reading
of it matched fragments of words against a short list, and against live
boards that went wrong in every direction at once:

  * plain "Remote" was read as a region that excluded you, so anyone who had
    said where they can work lost every role on We Work Remotely, RemoteOK
    and Jobicy;
  * "EMEA" excluded someone in South Africa, which EMEA contains;
  * "Remote, South Korea" and "Remote, US" were kept, because those
    spellings weren't on the list;
  * "Lausanne" was the USA, because the letters u-s-a are in it.

So this knows the actual places: countries and their other names, the
groupings adverts use (EMEA, APAC, LATAM, DACH, the EU…), US states and
Canadian provinces, and the cities that turn up most. It reads a location
into the countries it names, whether it is remote, and whether it is open to
anyone; `decide` then answers the one question that matters against where
you have said you can work.

What it cannot recognise it does not guess at: an unfamiliar town on a remote
role is kept for the fit score to judge, and never silently dropped.
"""
from __future__ import annotations

import re
from functools import lru_cache

# iso2|name|other names
_COUNTRY_ROWS = """
AF|Afghanistan
AX|Åland Islands|Aland Islands
AL|Albania
DZ|Algeria
AD|Andorra
AO|Angola
AG|Antigua and Barbuda
AR|Argentina
AM|Armenia
AU|Australia
AT|Austria|Österreich
AZ|Azerbaijan
BS|Bahamas
BH|Bahrain
BD|Bangladesh
BB|Barbados
BY|Belarus
BE|Belgium|Belgique;België
BZ|Belize
BJ|Benin
BM|Bermuda
BT|Bhutan
BO|Bolivia
BA|Bosnia and Herzegovina|Bosnia
BW|Botswana
BR|Brazil|Brasil
BN|Brunei
BG|Bulgaria
BF|Burkina Faso
BI|Burundi
CV|Cabo Verde|Cape Verde
KH|Cambodia
CM|Cameroon
CA|Canada
CF|Central African Republic
TD|Chad
CL|Chile
CN|China|Mainland China
CO|Colombia
KM|Comoros
CG|Congo|Republic of the Congo
CD|Democratic Republic of the Congo|DRC;DR Congo;Congo, The Democratic Republic of the
CR|Costa Rica
CI|Côte d'Ivoire|Cote d'Ivoire;Ivory Coast
HR|Croatia
CU|Cuba
CW|Curaçao|Curacao
CY|Cyprus
CZ|Czechia|Czech Republic
DK|Denmark|Danmark
DJ|Djibouti
DM|Dominica
DO|Dominican Republic
EC|Ecuador
EG|Egypt
SV|El Salvador
GQ|Equatorial Guinea
ER|Eritrea
EE|Estonia
SZ|Eswatini|Swaziland
ET|Ethiopia
FO|Faroe Islands
FJ|Fiji
FI|Finland|Suomi
FR|France
GF|French Guiana
GA|Gabon
GM|Gambia
GE|Georgia
DE|Germany|Deutschland
GH|Ghana
GI|Gibraltar
GR|Greece
GL|Greenland
GD|Grenada
GP|Guadeloupe
GT|Guatemala
GG|Guernsey
GN|Guinea
GW|Guinea-Bissau
GY|Guyana
HT|Haiti
VA|Holy See|Vatican City;Vatican;Holy See (Vatican City State)
HN|Honduras
HU|Hungary
IS|Iceland
IN|India
ID|Indonesia
IR|Iran
IQ|Iraq
IE|Ireland|Republic of Ireland
IM|Isle of Man
IL|Israel
IT|Italy|Italia
JM|Jamaica
JP|Japan
JE|Jersey
JO|Jordan
KZ|Kazakhstan
KE|Kenya
KI|Kiribati
XK|Kosovo
KW|Kuwait
KG|Kyrgyzstan
LA|Laos
LV|Latvia
LB|Lebanon
LS|Lesotho
LR|Liberia
LY|Libya
LI|Liechtenstein
LT|Lithuania
LU|Luxembourg
MG|Madagascar
MW|Malawi
MY|Malaysia
MV|Maldives
ML|Mali
MT|Malta
MQ|Martinique
MR|Mauritania
MU|Mauritius
YT|Mayotte
MX|Mexico|México
MD|Moldova
MC|Monaco
MN|Mongolia
ME|Montenegro
MA|Morocco
MZ|Mozambique
MM|Myanmar|Burma
NA|Namibia
NP|Nepal
NL|Netherlands|The Netherlands;Holland;Nederland
NC|New Caledonia
NZ|New Zealand|Aotearoa
NI|Nicaragua
NE|Niger
NG|Nigeria
KP|North Korea
MK|North Macedonia|Macedonia
NO|Norway|Norge
OM|Oman
PK|Pakistan
PS|Palestine|Palestine, State of
PA|Panama|Panamá
PG|Papua New Guinea
PY|Paraguay
PE|Peru|Perú
PH|Philippines|The Philippines
PL|Poland|Polska
PT|Portugal
PR|Puerto Rico
QA|Qatar
RE|Réunion|Reunion
RO|Romania
RU|Russia|Russian Federation
RW|Rwanda
KN|Saint Kitts and Nevis
LC|Saint Lucia
VC|Saint Vincent and the Grenadines
WS|Samoa
SM|San Marino
ST|Sao Tome and Principe
SA|Saudi Arabia|KSA
SN|Senegal
RS|Serbia
SC|Seychelles
SL|Sierra Leone
SG|Singapore
SX|Sint Maarten
SK|Slovakia
SI|Slovenia
SB|Solomon Islands
SO|Somalia
ZA|South Africa|Republic of South Africa;RSA;Suid-Afrika
KR|South Korea|Korea;Republic of Korea;Korea, Republic of
SS|South Sudan
ES|Spain|España
LK|Sri Lanka
SD|Sudan
SR|Suriname
SE|Sweden|Sverige
CH|Switzerland|Schweiz;Suisse
SY|Syria|Syrian Arab Republic
TW|Taiwan
TJ|Tajikistan
TZ|Tanzania
TH|Thailand
TL|Timor-Leste|East Timor
TG|Togo
TO|Tonga
TT|Trinidad and Tobago|Trinidad;Tobago
TN|Tunisia
TR|Turkey|Türkiye;Turkiye
TM|Turkmenistan
UG|Uganda
UA|Ukraine
AE|United Arab Emirates|Emirates
GB|United Kingdom|Great Britain;Britain;England;Scotland;Wales;Northern Ireland
US|United States|United States of America;America;U.S.A.;U.S.
UY|Uruguay
UZ|Uzbekistan
VU|Vanuatu
VE|Venezuela
VN|Vietnam|Viet Nam
YE|Yemen
ZM|Zambia
ZW|Zimbabwe
"""


def _s(codes: str) -> frozenset:
    return frozenset(codes.split())


EUROPE = _s("AL AD AT BY BE BA BG HR CY CZ DK EE FO FI FR DE GI GR GG HU IS IE IM IT JE XK LV LI "
            "LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB VA AX TR")
EU = _s("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE")
AFRICA = _s("DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR "
            "LY MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW RE YT")
NORTH_AFRICA = _s("DZ EG LY MA TN SD")
MIDDLE_EAST = _s("BH CY EG IR IQ IL JO KW LB OM PS QA SA SY TR AE YE")
ASIA = _s("AF AM AZ BH BD BT BN KH CN GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY MV MN MM NP "
          "KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TM AE UZ VN YE")
SE_ASIA = _s("BN KH ID LA MY MM PH SG TH TL VN")
OCEANIA = _s("AU NZ FJ PG WS TO VU SB KI NC")
APAC = (ASIA - MIDDLE_EAST - _s("AM AZ GE KZ KG TJ TM UZ AF")) | OCEANIA
NORTH_AMERICA = _s("US CA MX")
CENTRAL_AMERICA = _s("BZ CR SV GT HN NI PA")
CARIBBEAN = _s("AG BS BB CU DM DO GD HT JM KN LC VC TT PR CW BM SX GP MQ")
SOUTH_AMERICA = _s("AR BO BR CL CO EC GY PY PE SR UY VE GF")
LATAM = SOUTH_AMERICA | CENTRAL_AMERICA | _s("MX CU DO HT PR")
AMERICAS = NORTH_AMERICA | CENTRAL_AMERICA | CARIBBEAN | SOUTH_AMERICA
EMEA = EUROPE | MIDDLE_EAST | AFRICA
_BALTICS = _s("EE LV LT")
_BALKANS = _s("AL BA BG HR XK ME MK RO RS SI GR")
_NORDICS = _s("DK SE NO FI IS")

# the groupings adverts use, by every spelling of them that turns up
REGIONS = {
    "europe": EUROPE, "european union": EU, "eea": EU | _s("IS LI NO"),
    "european economic area": EU | _s("IS LI NO"),
    "emea": EMEA, "africa": AFRICA, "north africa": NORTH_AFRICA,
    "sub-saharan africa": AFRICA - NORTH_AFRICA, "sub saharan africa": AFRICA - NORTH_AFRICA,
    "southern africa": _s("ZA NA BW ZW MZ LS SZ ZM MW AO"),
    "east africa": _s("KE TZ UG RW BI ET SO DJ ER SS"),
    "west africa": _s("NG GH SN CI BJ BF CV GM GN GW LR ML MR NE SL TG"),
    "middle east": MIDDLE_EAST, "mena": MIDDLE_EAST | NORTH_AFRICA,
    "gcc": _s("BH KW OM QA SA AE"), "gulf": _s("BH KW OM QA SA AE"),
    "asia": ASIA, "southeast asia": SE_ASIA, "south east asia": SE_ASIA, "south-east asia": SE_ASIA,
    "apac": APAC, "asia pacific": APAC, "asia-pacific": APAC, "apj": APAC,
    "oceania": OCEANIA, "australasia": _s("AU NZ"), "anz": _s("AU NZ"),
    "north america": NORTH_AMERICA, "northern america": NORTH_AMERICA,
    "central america": CENTRAL_AMERICA, "south america": SOUTH_AMERICA,
    "latin america": LATAM, "latam": LATAM, "americas": AMERICAS, "the americas": AMERICAS,
    "caribbean": CARIBBEAN,
    "dach": _s("DE AT CH"), "nordics": _NORDICS, "nordic countries": _NORDICS,
    "scandinavia": _s("DK SE NO"), "benelux": _s("BE NL LU"),
    "baltics": _BALTICS, "baltic states": _BALTICS, "balkans": _BALKANS, "iberia": _s("ES PT"),
    "eastern europe": _s("PL CZ SK HU RO BG UA BY MD RU") | _BALTICS | _BALKANS,
    "central europe": _s("DE AT CH PL CZ SK HU SI"),
    "central and eastern europe": _s("PL CZ SK HU RO BG UA BY MD AT SI") | _BALTICS | _BALKANS,
    "cee": _s("PL CZ SK HU RO BG UA BY MD AT SI") | _BALTICS | _BALKANS,
    "western europe": _s("GB IE FR BE NL LU DE AT CH ES PT IT") | _NORDICS,
    "southern europe": _s("ES PT IT GR MT CY HR"),
    "uk and ireland": _s("GB IE"), "british isles": _s("GB IE"),
}
# short codes, matched only as written (upper case), so "us" in a sentence,
# "in", "or" and "me" are never taken for places
_CODES = {
    "US": _s("US"), "USA": _s("US"), "UK": _s("GB"), "GB": _s("GB"), "UAE": _s("AE"),
    "EU": EU, "EMEA": EMEA, "APAC": APAC, "LATAM": LATAM, "MENA": MIDDLE_EAST | NORTH_AFRICA,
    "DACH": _s("DE AT CH"), "ANZ": _s("AU NZ"), "CEE": REGIONS["cee"], "GCC": REGIONS["gcc"],
    "EEA": REGIONS["eea"], "NZ": _s("NZ"), "NYC": _s("US"), "SF": _s("US"), "KSA": _s("SA"),
    "RSA": _s("ZA"), "DRC": _s("CD"), "PRC": _s("CN"), "ROK": _s("KR"),
}

_US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC", "washington dc": "DC",
    "washington d.c.": "DC",
}
_US_CODES = set(_US_STATES.values()) | {"GA"}
_CA_PROVINCES = {
    "ontario": "ON", "quebec": "QC", "québec": "QC", "british columbia": "BC", "alberta": "AB",
    "manitoba": "MB", "saskatchewan": "SK", "nova scotia": "NS", "new brunswick": "NB",
    "newfoundland": "NL", "prince edward island": "PE",
}
_CA_CODES = {"ON", "QC", "BC", "AB", "MB", "NS", "NB", "PE"}
# provinces and states elsewhere that adverts name instead of a town
_OTHER_AREAS = {
    "gauteng": "ZA", "western cape": "ZA", "eastern cape": "ZA", "northern cape": "ZA",
    "kwazulu-natal": "ZA", "kwazulu natal": "ZA", "kzn": "ZA", "free state": "ZA",
    "limpopo": "ZA", "mpumalanga": "ZA", "north west province": "ZA",
    "new south wales": "AU", "victoria": "AU", "queensland": "AU", "western australia": "AU",
    "bavaria": "DE", "bayern": "DE", "north rhine-westphalia": "DE", "catalonia": "ES",
    "karnataka": "IN", "maharashtra": "IN", "tamil nadu": "IN", "telangana": "IN",
    "odisha": "IN", "kerala": "IN", "gujarat": "IN", "uttar pradesh": "IN", "haryana": "IN",
}

# city|iso2|metro it belongs to (when it's a suburb or a second name)
_CITY_ROWS = """
new york|US;new york city|US;manhattan|US;brooklyn|US;san francisco|US;bay area|US
silicon valley|US;los angeles|US;chicago|US;boston|US;seattle|US;austin|US;denver|US
atlanta|US;dallas|US;houston|US;miami|US;philadelphia|US;phoenix|US;san diego|US
san jose|US;portland|US;minneapolis|US;detroit|US;nashville|US;raleigh|US;charlotte|US
salt lake city|US;pittsburgh|US;palo alto|US;mountain view|US;sunnyvale|US;menlo park|US
redmond|US;cupertino|US;santa clara|US;oakland|US;san mateo|US;santa monica|US;irvine|US
sacramento|US;las vegas|US;orlando|US;tampa|US;st. louis|US;st louis|US;kansas city|US
columbus|US;cincinnati|US;cleveland|US;indianapolis|US;milwaukee|US;baltimore|US
jersey city|US;boulder|US;durham|US;ann arbor|US;madison|US;new orleans|US;honolulu|US
toronto|CA;vancouver|CA;montreal|CA;montréal|CA;ottawa|CA;calgary|CA;edmonton|CA
waterloo|CA;winnipeg|CA;halifax|CA;mississauga|CA
london|GB;manchester|GB;edinburgh|GB;glasgow|GB;birmingham|GB;bristol|GB;leeds|GB
cambridge|GB;oxford|GB;belfast|GB;cardiff|GB;liverpool|GB;newcastle|GB;reading|GB
sheffield|GB;nottingham|GB;brighton|GB;dunfermline|GB
dublin|IE;cork|IE;galway|IE;limerick|IE
berlin|DE;munich|DE;münchen|DE;hamburg|DE;frankfurt|DE;cologne|DE;köln|DE;stuttgart|DE
düsseldorf|DE;dusseldorf|DE;leipzig|DE;dresden|DE;nuremberg|DE;nürnberg|DE;hannover|DE
bonn|DE;karlsruhe|DE;lüneburg|DE
paris|FR;lyon|FR;marseille|FR;toulouse|FR;nantes|FR;bordeaux|FR;lille|FR;nice|FR
amsterdam|NL;rotterdam|NL;utrecht|NL;eindhoven|NL;the hague|NL;den haag|NL
brussels|BE;antwerp|BE;ghent|BE;luxembourg city|LU
madrid|ES;barcelona|ES;valencia|ES;malaga|ES;málaga|ES;seville|ES;bilbao|ES
lisbon|PT;lisboa|PT;porto|PT
milan|IT;milano|IT;rome|IT;roma|IT;turin|IT;bologna|IT;florence|IT
zurich|CH;zürich|CH;geneva|CH;basel|CH;lausanne|CH;bern|CH;zug|CH;lugano|CH
vienna|AT;wien|AT;graz|AT;linz|AT
stockholm|SE;gothenburg|SE;malmö|SE;malmo|SE;copenhagen|DK;aarhus|DK;oslo|NO;bergen|NO
helsinki|FI;espoo|FI;tampere|FI;reykjavik|IS
warsaw|PL;krakow|PL;kraków|PL;wroclaw|PL;wrocław|PL;gdansk|PL;gdańsk|PL;poznan|PL;lodz|PL
prague|CZ;brno|CZ;budapest|HU;bucharest|RO;cluj|RO;cluj-napoca|RO;sofia|BG
athens|GR;thessaloniki|GR;istanbul|TR;ankara|TR;izmir|TR
kyiv|UA;kiev|UA;lviv|UA;kharkiv|UA;moscow|RU;saint petersburg|RU;st. petersburg|RU;minsk|BY
tallinn|EE;riga|LV;vilnius|LT;kaunas|LT;belgrade|RS;zagreb|HR;ljubljana|SI;bratislava|SK
tirana|AL;sarajevo|BA;skopje|MK;chisinau|MD;valletta|MT;nicosia|CY;limassol|CY
tel aviv|IL;jerusalem|IL;haifa|IL;dubai|AE;abu dhabi|AE;riyadh|SA;jeddah|SA;doha|QA
kuwait city|KW;manama|BH;muscat|OM;amman|JO;beirut|LB;cairo|EG;alexandria|EG
bangalore|IN;bengaluru|IN;hyderabad|IN;pune|IN;mumbai|IN;delhi|IN;new delhi|IN
gurgaon|IN;gurugram|IN;noida|IN;chennai|IN;kolkata|IN;ahmedabad|IN;jaipur|IN;kochi|IN
karachi|PK;lahore|PK;islamabad|PK;dhaka|BD;colombo|LK;kathmandu|NP
kuala lumpur|MY;penang|MY;jakarta|ID;bali|ID;bangkok|TH;ho chi minh city|VN;hanoi|VN
manila|PH;cebu|PH;beijing|CN;shanghai|CN;shenzhen|CN;guangzhou|CN;hangzhou|CN;chengdu|CN
hong kong|HK;macau|MO;macao|MO;taipei|TW;tokyo|JP;osaka|JP;kyoto|JP;seoul|KR;busan|KR
sydney|AU;melbourne|AU;brisbane|AU;perth|AU;adelaide|AU;canberra|AU;hobart|AU
alice springs|AU;auckland|NZ;wellington|NZ;christchurch|NZ
johannesburg|ZA;joburg|ZA|johannesburg;jhb|ZA|johannesburg;sandton|ZA|johannesburg
randburg|ZA|johannesburg;rosebank|ZA|johannesburg;midrand|ZA|johannesburg
roodepoort|ZA|johannesburg;fourways|ZA|johannesburg;bryanston|ZA|johannesburg
parktown|ZA|johannesburg;braamfontein|ZA|johannesburg;woodmead|ZA|johannesburg
bedfordview|ZA|johannesburg;kempton park|ZA|johannesburg;soweto|ZA|johannesburg
cape town|ZA;cpt|ZA|cape town;bellville|ZA|cape town;century city|ZA|cape town
claremont|ZA|cape town;durbanville|ZA|cape town;stellenbosch|ZA;paarl|ZA;george|ZA
pretoria|ZA;tshwane|ZA|pretoria;centurion|ZA|pretoria;hatfield|ZA|pretoria
durban|ZA;umhlanga|ZA|durban;ethekwini|ZA|durban;westville|ZA|durban;pinetown|ZA|durban
pietermaritzburg|ZA;port elizabeth|ZA;gqeberha|ZA|port elizabeth;east london|ZA
bloemfontein|ZA;polokwane|ZA;nelspruit|ZA;mbombela|ZA|nelspruit;kimberley|ZA
rustenburg|ZA;potchefstroom|ZA;richards bay|ZA
lagos|NG;abuja|NG;nairobi|KE;mombasa|KE;accra|GH;casablanca|MA;rabat|MA;tunis|TN
addis ababa|ET;kigali|RW;kampala|UG;dar es salaam|TZ;lusaka|ZM;harare|ZW;gaborone|BW
windhoek|NA;maputo|MZ;dakar|SN;abidjan|CI;luanda|AO;port louis|MU
são paulo|BR;sao paulo|BR;rio de janeiro|BR;belo horizonte|BR;curitiba|BR;brasília|BR
florianópolis|BR;florianopolis|BR;porto alegre|BR;buenos aires|AR;córdoba|AR;rosario|AR
santiago|CL;bogotá|CO;bogota|CO;medellín|CO;medellin|CO;lima|PE;quito|EC
mexico city|MX;ciudad de méxico|MX;guadalajara|MX;monterrey|MX;montevideo|UY
caracas|VE;panama city|PA;san josé|CR;santo domingo|DO;havana|CU;kingston|JM
"""

_REMOTE = re.compile(
    r"\b(remote(?:ly)?|anywhere|world[- ]?wide|global(?:ly)?|work(?:ing)? from home|wfh|"
    r"distributed|telecommut\w*|home[- ]based|virtual|location independent)\b", re.I)
_OPEN = re.compile(
    r"\b(world[- ]?wide|anywhere|global(?:ly)?|international(?:ly)?|any country|all countries|"
    r"any location|location independent|no location restrictions?)\b", re.I)
# a working-hours wish, not a rule about where you live: "USA timezones",
# "Time zone: CET (+/- 3 hours)", "GMT+2", "overlap with EST"
_TZ = re.compile(
    r"(?:time ?zones?\s*:?[^,;|]*|[^,;|]*\btime ?zones?\b|[^,;|]*\bworking hours\b[^,;|]*|"
    r"[^,;|]*\boverlap\b[^,;|]*|"
    r"\b(?:gmt|utc|cet|cest|eet|eest|wet|bst|est|edt|cst|cdt|mst|mdt|pst|pdt|ist|sast|aest|aedt|"
    r"jst|sgt|hkt)\b(?:\s*\(?[+\-−±/ ]*\d{1,2}(?::\d\d)?(?:\s*(?:hours?|hrs?|h))?\)?)*)", re.I)
# words that say how, not where
_FILLER = re.compile(
    r"\b(remote(?:ly)?|hybrid|on[- ]?site|in[- ]?office|office|offices|only|based|home|your|our|"
    r"the|in|of|from|within|across|or|and|work(?:ing)?|role|roles|position|hq|headquarters|"
    r"head office|full[- ]?time|part[- ]?time|contract|permanent|flexible|first|friendly|ok|"
    r"okay|possible|option(?:al)?|eligible|candidates?|residents?|citizens?|must|be|to|is|are|"
    r"for|with|any|all|other|area|areas|region|regions|metro|greater|city|county|state|"
    r"province|country|countries|locations?|multiple|various|several|preferred|required|"
    r"north|south|east|west|northern|southern|eastern|western|central|suburbs?|cbd|downtown|"
    r"anywhere|world[- ]?wide|global(?:ly)?|world|international(?:ly)?|distributed|virtual|"
    r"telecommute|wfh|us[- ]based|uk[- ]based|days?|week|per|a|an|at|on|up|plus|etc)\b", re.I)


def _build():
    countries, names = {}, {}
    for row in _COUNTRY_ROWS.strip().splitlines():
        parts = row.split("|")
        iso, name = parts[0], parts[1]
        countries[iso] = name
        for n in [name] + (parts[2].split(";") if len(parts) > 2 else []):
            names[n.lower()] = ("country", frozenset([iso]), "")
    for n, cs in REGIONS.items():
        names[n] = ("region", cs, "")
    for n in _US_STATES:
        names[n] = ("area", frozenset(["US"]), "")
    for n in _CA_PROVINCES:
        names[n] = ("area", frozenset(["CA"]), "")
    for n, iso in _OTHER_AREAS.items():
        names[n] = ("area", frozenset([iso]), "")
    for chunk in _CITY_ROWS.replace("\n", ";").split(";"):
        if not chunk.strip():
            continue
        bits = chunk.strip().split("|")
        names[bits[0]] = ("city", frozenset([bits[1]]), bits[2] if len(bits) > 2 else bits[0])
    # Georgia is a country and a US state; without a town beside it, either
    names["georgia"] = ("area", frozenset(["GE", "US"]), "")
    # longest first, so "South Africa" is never read as "Africa", "New Mexico"
    # as Mexico, "Northern Ireland" as Ireland, or "Guinea-Bissau" as Guinea
    ordered = sorted(names, key=len, reverse=True)
    rx = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in ordered) + r")(?![\w-])", re.I)
    codes = re.compile(r"(?<![\w.])(?:U\.S\.A\.|U\.S\.|U\.K\.|" + "|".join(sorted(_CODES, key=len, reverse=True))
                       + r")(?![\w])")
    return countries, names, rx, codes


COUNTRIES, _NAMES, _NAME_RX, _CODE_RX = _build()
_DOTTED = {"U.S.A.": _s("US"), "U.S.": _s("US"), "U.K.": _s("GB")}
_STATE_CODE = re.compile(r"(?:,|^|\(|-)\s*([A-Z]{2})(?=\s*(?:,|$|\)|\(|-|;|/))")


# text decoded with the wrong alphabet: the lead bytes of two- and three-byte
# UTF-8 shown as Latin letters, then one to three continuation bytes
_NBSP = chr(0xA0)
_MOJI_HINT = re.compile("[" + chr(0xC3) + chr(0xC2) + chr(0xE2) + "]")
_MOJI_RUN = re.compile("[" + chr(0xC3) + chr(0xC2) + chr(0xE2) + "]["
                       + chr(0x80) + "-" + chr(0xFF)
                       + "".join(chr(c) for c in (0x152, 0x153, 0x160, 0x161, 0x178, 0x17D, 0x17E,
                                                  0x192, 0x2C6, 0x2DC, 0x20AC, 0x2122))
                       + chr(0x2013) + "-" + chr(0x203A) + "]{1,3}")
_MOJI_LONE = re.compile(chr(0xC2) + "(?=" + chr(92) + "s|$|<)")


def country_name(iso: str) -> str:
    return COUNTRIES.get(iso, iso)


def fix_text(s: str) -> str:
    """Undo text that was decoded with the wrong alphabet ("MÃ¼nchen",
    "donâ€™t"). Boards serve it that way inside otherwise good data, and it
    went straight into letters and CVs. Text that is fine is left exactly as
    it was."""
    if not s or not _MOJI_HINT.search(s):
        return s
    try:
        fixed = s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            fixed = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            # mixed text: repair the pieces that can be, leave the rest
            def one(m):
                for enc in ("cp1252", "latin-1"):
                    try:
                        return m.group(0).encode(enc).decode("utf-8")
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        continue
                return m.group(0)
            fixed = _MOJI_RUN.sub(one, s)
    # the commonest leftover: a non-breaking space that became A-circumflex
    # and an ordinary space
    fixed = _MOJI_LONE.sub("", fixed)
    return fixed.replace(_NBSP, " ")


@lru_cache(maxsize=8192)
def read_place(loc: str) -> dict:
    """What a location says: {'remote', 'open', 'countries', 'kinds', 'cities',
    'unknown', 'only_regions'}.

    `countries` is every country it names or that its regions cover;
    `unknown` is what's left that couldn't be placed; `only_regions` is true
    when it names countries and groupings and no town or state (a list of
    where a remote worker may live, not an office)."""
    text = fix_text(str(loc or "")).strip()
    out = {"remote": False, "open": False, "countries": frozenset(), "kinds": (),
           "cities": (), "unknown": (), "only_regions": False, "text": text}
    if not text:
        out["open"] = True
        return out
    out["remote"] = bool(_REMOTE.search(text))
    is_open = bool(_OPEN.search(text))
    work = _TZ.sub(" ", text)
    found, kinds, cities = set(), [], []

    def take_code(m):
        tok = m.group(0)
        found.update(_DOTTED.get(tok) or _CODES[tok])
        kinds.append("region" if len(_DOTTED.get(tok) or _CODES[tok]) > 1 else "country")
        return " , "
    work = _CODE_RX.sub(take_code, work)

    def take_name(m):
        kind, cs, metro = _NAMES[m.group(0).lower()]
        found.update(cs)
        kinds.append(kind)
        if kind == "city":
            cities.append(metro)
        return " , "
    work = _NAME_RX.sub(take_name, work)
    # "Scotch Plains, NJ", "Toronto, ON": a two-letter code after a comma. A
    # town we know settles it ("Berlin, DE"); otherwise a US state or a
    # Canadian province before a country code, as adverts write them.
    def take_state(m):
        code = m.group(1)
        if code in _CA_CODES:
            found.add("CA")
        elif code in _US_CODES:
            if not any(k == "city" for k in kinds) or "US" in found:
                found.add("US")
        elif code in COUNTRIES:
            found.add(code)
        else:
            return m.group(0)
        kinds.append("area")
        return " , "
    work = _STATE_CODE.sub(take_state, work)
    rest = _FILLER.sub(" ", work)
    unknown = [t for t in (re.sub(r"[^\w' .&-]", " ", x).strip(" .-&'")
                           for x in re.split(r"[,;|/()\[\]•·:]|\s[-–—]\s", rest))
               if len(t) > 2 and not t.isdigit()]
    out.update(countries=frozenset(found), kinds=tuple(kinds), cities=tuple(cities),
               unknown=tuple(unknown),
               open=is_open or (not found and not unknown),
               only_regions=bool(found) and not unknown
               and all(k in ("country", "region") for k in kinds))
    return out


def allowed_from(places, home: str = "") -> dict:
    """Where you can work, from what you've written: {'anywhere', 'work',
    'home', 'cities', 'raw', 'declared'}.

    `work` is the countries you named (or that a grouping you named covers):
    a role there suits you, remote or not. `home` adds the country you live
    in, which is enough for a remote role limited to it. `cities` and `raw`
    are the towns and anything else you wrote, matched against an office's
    address."""
    work, home_c, cities, raw, anywhere = set(), set(), set(), [], False
    for item in places or []:
        s = str(item or "").strip()
        if not s or s.lower() in ("remote", "remotely", "wfh", "work from home"):
            continue
        p = read_place(s)
        if _OPEN.search(s):
            anywhere = True
            continue
        if p["countries"] and all(k in ("country", "region") for k in p["kinds"]) and not p["unknown"]:
            work |= p["countries"]
        elif p["countries"]:
            home_c |= p["countries"]          # a town or a province of yours
            cities |= set(p["cities"])
            raw.append(s.lower())
        else:
            raw.append(s.lower())
    if home:
        hp = read_place(home)
        home_c |= hp["countries"]
    return {"anywhere": anywhere, "work": frozenset(work), "home": frozenset(home_c | work),
            "cities": frozenset(cities), "raw": tuple(raw),
            "declared": bool(work or raw or cities)}


def _names(codes, limit: int = 3) -> str:
    codes = set(codes)
    for label, group in (("Europe", EUROPE), ("the EU", EU), ("Latin America", LATAM),
                         ("the Americas", AMERICAS), ("Asia-Pacific", APAC), ("EMEA", EMEA)):
        if codes == set(group):
            return label
    ordered = sorted(country_name(c) for c in codes)
    if len(ordered) > limit:
        return ", ".join(ordered[:limit]) + f" and {len(ordered) - limit} more"
    return ", ".join(ordered)


def _where(p: dict, named, listed: bool) -> str:
    """The places a role is limited to, as a person would say them: the
    countries when there are a few, the advert's own words when it lists
    regions ("LATAM, Europe, USA, Canada, APAC")."""
    if len(named) <= 3 or listed:
        return _names(named)
    own = re.sub(r"\s{2,}", " ", _REMOTE.sub("", p["text"])).strip(" ,;-()")
    return own if 0 < len(own) <= 80 else _names(named)


def decide(loc: str, allowed: dict, *, remote_only: bool = True, remote: bool = False,
           countries=None, default_country: str = "") -> tuple:
    """(keep, category, detail) for one role's location against where you
    can work.

    category is one of '', 'not remote', 'region excludes you', 'location not
    in your list' (the reasons a run report groups by); detail is the
    sentence a person reads: "open only to people in Canada, United States".

    `countries` is a list the board gave outright (the countries a remote
    role is open to); `remote` says the board marked it remote;
    `default_country` is the country of a board that serves one."""
    p = read_place(loc)
    named = set(p["countries"])
    listed = False
    if countries:
        extra = set()
        for c in countries:
            c = str(c or "").strip()
            if len(c) == 2 and c.upper() in COUNTRIES:
                extra.add(c.upper())
            else:
                extra |= read_place(c)["countries"]
        if extra:
            named, listed = extra, True
    # "LATAM, Canada, USA", or a country alone, with no town in it: a list of
    # where a remote worker may live, not an office. So is a list the board
    # gave outright.
    is_remote = p["remote"] or bool(remote) or listed or p["only_regions"]
    if p["open"] and not listed and not (default_country and not is_remote):
        return True, "", ""
    if allowed.get("anywhere"):
        return True, "", ""
    if not named and default_country and not _OPEN.search(p["text"]):
        named = {default_country.upper()}
    low = p["text"].lower()
    mine_remote = allowed["home"]
    mine_office = allowed["work"]
    if named:
        if is_remote and named & mine_remote:
            return True, "", ""
        if named & mine_office:
            return True, "", ""
        # an office in a town of yours, or in the metro it belongs to
        if not is_remote and named & mine_remote and (
                set(p["cities"]) & allowed["cities"] or any(r in low for r in allowed["raw"])):
            return True, "", ""
        if not allowed["home"] and not allowed["declared"]:
            # nothing said about where you are: don't guess for a remote role
            if is_remote:
                return True, "", ""
            return (False, "not remote", f"on site in {p['text']}") if remote_only \
                else (True, "", "")
        if is_remote:
            return False, "region excludes you", f"open only to people in {_where(p, named, listed)}"
        if remote_only:
            return False, "not remote", f"on site in {p['text'] or _names(named)}"
        return False, "location not in your list", f"on site in {p['text'] or _names(named)}"
    # a place it couldn't put on the map
    if any(r in low for r in allowed["raw"]):
        return True, "", ""
    if is_remote:
        return True, "", ""           # unfamiliar, and remote: the fit score judges it
    if remote_only:
        return False, "not remote", f"on site in {p['text']}"
    if allowed["declared"]:
        return False, "location not in your list", f"on site in {p['text']}"
    return True, "", ""


# --------------------------------------------------------------------------- #
#  what the advert itself says about who may apply
# --------------------------------------------------------------------------- #
_PLACE = r"(?P<place>(?:[A-Z][\w.'&-]*|the|of|and|or|,|/)(?:\s+(?:[A-Z][\w.'&-]*|the|of|and|or|/)|\s*,\s*(?:[A-Z][\w.'&-]*|the)){0,7})"
_ELIGIBLE = [
    # "must be based in the United States", "need to reside in the UK or Ireland"
    (re.compile(r"\b(?:must|need(?:s)? to|required to|have to|has to|should)\s+(?:currently\s+)?"
                r"(?:be\s+)?(?:legally\s+|physically\s+|permanently\s+)?"
                r"(?:based|located|resid(?:e|ing|ent)|liv(?:e|ing)|domiciled)\s+(?:in|within)\s+" + _PLACE),
     "says you must be based in {}"),
    # "authorized to work in the US", "right to work in the UK"
    (re.compile(r"\b(?:authori[sz](?:ed|ation)|eligib(?:le|ility)|legally\s+(?:able|permitted|entitled|allowed)|"
                r"(?:the\s+|a\s+|full\s+|valid\s+|existing\s+|unrestricted\s+)?(?:legal\s+)?right|permission|permit)"
                r"\s+to\s+(?:live\s+and\s+)?work\s+(?:\w+\s+){0,2}?(?:in|within)\s+" + _PLACE),
     "asks for the right to work in {}"),
    # "open to candidates in Canada only", "only hiring in the United States"
    (re.compile(r"\b(?:only|exclusively)\s+(?:open\s+to|considering|accepting|hiring|available\s+to|for)\s+"
                r"(?:\w+\s+){0,3}?(?:in|from|within)\s+" + _PLACE),
     "is open only to people in {}"),
    (re.compile(r"\b(?:open|available|limited|restricted)\s+(?:only\s+)?to\s+(?:candidates|applicants|residents|"
                r"people|those|individuals)\s+(?:who\s+are\s+)?(?:currently\s+)?(?:based\s+|located\s+|residing\s+|living\s+)?"
                r"(?:in|within)\s+" + _PLACE + r"(?:\s+only)?"),
     "is open only to people in {}"),
    # "US-based only", "UK residents only", "Canadian citizens only"
    (re.compile(r"(?P<place>\b(?:U\.S\.|US|USA|UK|EU|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?))[- ](?:based\s+)?"
                r"(?:candidates|applicants|residents|citizens)?\s*only\b"),
     "is open only to people in {}"),
    # "candidates must be US citizens", "U.S. citizenship is required"
    (re.compile(r"(?P<place>\b(?:U\.S\.|US|USA|United States))\s+(?:citizen(?:ship|s)?|person(?:s)?)\b[^.]{0,40}?"
                r"\b(?:required|only|must|mandatory)\b"),
     "requires citizenship of {}"),
    (re.compile(r"\b(?:must|required to)\s+(?:be|hold|have)\s+(?:a\s+|an\s+)?(?P<place>U\.S\.|US|USA|United States)\s+"
                r"citizen"),
     "requires citizenship of {}"),
]
_NO_SPONSOR = re.compile(
    r"\b(?:(?:no|not|unable\s+to|cannot|can(?:'|’)?t|can\s+not|do(?:es)?\s+not|don(?:'|’)?t|doesn(?:'|’)?t|"
    r"will\s+not|won(?:'|’)?t|not\s+able\s+to|not\s+in\s+a\s+position\s+to|unfortunately)\s+"
    r"(?:\w+\s+){0,4}?(?:visa\s+|work\s+permit\s+|immigration\s+|employment\s+)?sponsor(?:ship|ing)?"
    r"|without\s+(?:the\s+need\s+for\s+|requiring\s+|needing\s+|any\s+)?(?:\w+\s+){0,2}?sponsorship"
    r"|sponsorship\s+(?:is\s+|will\s+)?(?:not|n(?:'|’)t|unavailable)\s*(?:be\s+)?(?:available|offered|provided|possible)?"
    r"|not\s+eligible\s+for\s+(?:visa\s+)?sponsorship)\b", re.I)
_CLEARANCE = re.compile(r"\b(?:security\s+clearance|TS/SCI|top\s+secret|secret\s+clearance|public\s+trust\s+clearance|"
                        r"polygraph)\b", re.I)


def eligibility(text: str) -> dict:
    """What an advert states about who may apply: {'countries', 'says',
    'no_sponsorship', 'evidence'}.

    Only explicit statements count: "must be based in the United States",
    "right to work in the UK", "US citizens only", "we are unable to sponsor
    visas". A company describing where its offices are is not one."""
    text = fix_text(str(text or ""))
    countries, says, evidence = set(), "", ""
    for rx, phrase in _ELIGIBLE:
        for m in rx.finditer(text):
            place = m.group("place").strip(" ,/")
            p = read_place(place)
            if not p["countries"] or p["open"]:
                continue
            countries |= p["countries"]
            if not says:
                says = phrase.format(_names(p["countries"]))
                evidence = " ".join(text[max(0, m.start() - 30):m.end() + 30].split())
    ns = _NO_SPONSOR.search(text)
    clearance = _CLEARANCE.search(text)
    if clearance and not countries and re.search(r"\b(U\.S\.|US|USA|United States|federal|DoD)\b", text):
        countries.add("US")
        says = "needs a US security clearance"
        evidence = " ".join(text[max(0, clearance.start() - 40):clearance.end() + 40].split())
    return {"countries": frozenset(countries), "says": says,
            "no_sponsorship": bool(ns),
            "evidence": evidence or (" ".join(text[max(0, ns.start() - 40):ns.end() + 40].split()) if ns else "")}


def blocked_by_advert(text: str, allowed: dict, role_countries=()) -> str:
    """'' if nothing in the advert rules you out, else the reason in a
    sentence. `role_countries` is where the role itself is (from its location):
    "no sponsorship" only matters when that isn't somewhere you can work."""
    if allowed.get("anywhere"):
        return ""
    e = eligibility(text)
    mine = set(allowed.get("home") or ())
    if not mine:
        return ""                      # you haven't said where you are: nothing to compare
    if e["countries"] and not (e["countries"] & mine):
        return f"the advert {e['says']}"
    if e["no_sponsorship"]:
        where = set(role_countries or ())
        if where and not (where & mine):
            return (f"the advert offers no visa sponsorship, and the role is in "
                    f"{_names(where)}")
    return ""
