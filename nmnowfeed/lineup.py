"""NM Now curated lineup — v1.

One row per channel: (ntv_name, number, display, short, category, epg_id).

`ntv_name` is the exact `channel_name` in NTV's /api/get-channels catalog (Titan server,
code=us). The builder looks the stream up by that key — if NTV renames a channel, the
build logs it as MISSING (channel dropped from that build) rather than guessing.

`epg_id` is the epg.pw XMLTV channel id. None = no schedule source; the channel still
publishes with a playable stream and the app fills its row with "No Program Information".

Numbers are stable labels, deliberately gappy (dropped channels free their number for
good). Categories are free-form ids matching the categories array we publish; `recents`
and `all` are reserved by the app and never used here.

Judgment calls worth remembering:
- ABC -> National Feed (464902), NBC -> NBC East Stream (465059), CBS -> CBS West
  (464830). epg.pw has no national FOX feed at all -> FOX stays unmapped.
- NESN -> NESN+ (496625): epg.pw carries only the overflow feed, not main NESN. A close
  schedule beats none.
- beIN SPORTS 1/2/3 dropped: "beIN SPORTS" (exact epg.pw twin 464754) covers the
  franchise; the numbered feeds are dup clutter with no US EPG twin.
- MLB team channels map to epg.pw's "MLB - <Team>" virtual channels — these carry the
  RSN schedule for that market.
- ESPN's catalog name is "ESPN+ USA"; displayed as plain "ESPN".
"""

Category = tuple[str, str, str]  # id, label, icon

CATEGORIES: list[Category] = [
    ("networks", "Networks", "networks"),
    ("news", "News", "news"),
    ("sports", "Sports", "sports"),
    ("entertainment", "Entertainment", "entertainment"),
    ("documentary", "Documentary", "documentary"),
    ("kids", "Kids", "kids"),
    ("premium", "Movies & Premium", "premium"),
    ("spanish", "Español", "spanish"),
]

Row = tuple[str, str, str, str, str, str]

LINEUP: list[Row] = [
    # --- Networks 1xx ---
    ("ABC", "101", "ABC", "net", "networks", "464902"),
    ("CBS", "102", "CBS", "cbs", "networks", "464830"),
    ("NBC", "103", "NBC", "nbc", "networks", "465059"),
    ("FOX", "104", "FOX", "fox", "networks", ""),
    # --- News 2xx ---
    ("FOX News", "201", "FOX News", "fnc", "news", "465372"),
    ("CNN", "202", "CNN", "cnn", "news", "464857"),
    ("CNBC", "203", "CNBC", "cnbc", "news", "464791"),
    # --- Sports, national 3xx ---
    ("ESPN+ USA", "301", "ESPN", "espn", "sports", "465198"),
    ("ESPN 2", "302", "ESPN2", "esp2", "sports", "465373"),
    ("ESPN News", "303", "ESPNews", "espn", "sports", "465410"),
    ("ESPN U", "304", "ESPNU", "espu", "sports", "465108"),
    ("FOX Sports 1", "305", "FS1", "fs1", "sports", "465291"),
    ("beIN SPORTS", "306", "beIN Sports", "bein", "sports", "464754"),
    ("Tennis Channel", "309", "Tennis Channel", "ten", "sports", "465236"),
    ("MLB Network", "310", "MLB Network", "mlb", "sports", "465239"),
    ("NBA TV", "311", "NBA TV", "nba", "sports", "464912"),
    ("NFL Network", "312", "NFL Network", "nfl", "sports", "465311"),
    ("NHL Network", "313", "NHL Network", "nhl", "sports", "465348"),
    ("TUDN", "314", "TUDN", "tudn", "sports", "465174"),
    ("FOX Soccer Plus", "315", "FOX Soccer Plus", "fsp", "sports", "465214"),
    ("Willow Cricket", "316", "Willow Cricket", "wil", "sports", "465010"),
    ("ACC Network", "317", "ACC Network", "acc", "sports", "464879"),
    ("SEC Network", "318", "SEC Network", "sec", "sports", "465266"),
    ("Marquee Sports Network", "319", "Marquee Sports", "marq", "sports", "465271"),
    ("Space City Home Network", "320", "Space City", "schn", "sports", "465220"),
    ("Monumental Sports Network", "321", "Monumental", "mon", "sports", "465347"),
    ("CBS Sports Golazo", "322", "CBS Sports Golazo", "gol", "sports", "562308"),
    ("WWE", "323", "WWE Network", "wwe", "sports", "558129"),
    ("GOLF TV", "324", "GOLF TV", "golf", "sports", ""),
    ("Astro Cricket", "325", "Astro Cricket", "astro", "sports", ""),
    # --- Sports, regional 33x-36x ---
    ("MASN", "330", "MASN", "masn", "sports", "465409"),
    ("MSG", "331", "MSG", "msg", "sports", "465033"),
    ("NESN", "332", "NESN", "nesn", "sports", "496625"),
    ("SportsNet New York", "333", "SNY", "sny", "sports", "464777"),
    ("Yes Network", "334", "YES Network", "yes", "sports", "496607"),
    ("Altitude", "335", "Altitude Sports", "alt", "sports", "465288"),
    ("Chicago Sports Network", "336", "Chicago Sports Net", "chsn", "sports", "465058"),
    ("Red Bull", "337", "Red Bull TV", "rbt", "sports", ""),
    ("Arizona Diamondbacks", "340", "AZ Diamondbacks", "ari", "sports", "465596"),
    ("Atlanta Braves", "341", "Atlanta Braves", "atl", "sports", "465580"),
    ("Baltimore Orioles", "342", "Baltimore Orioles", "bal", "sports", "465732"),
    ("Boston Red Sox", "343", "Boston Red Sox", "bos", "sports", "465749"),
    ("Chicago Cubs", "344", "Chicago Cubs", "chc", "sports", "465534"),
    ("Chicago White Sox", "345", "Chicago White Sox", "cws", "sports", "465665"),
    ("Cincinnati Reds", "346", "Cincinnati Reds", "cin", "sports", "465509"),
    ("Cleveland Guardians", "347", "Cleveland Guardians", "cle", "sports", "465558"),
    ("Colorado Rockies", "348", "Colorado Rockies", "col", "sports", "465569"),
    ("Detroit Tigers", "349", "Detroit Tigers", "det", "sports", "465712"),
    ("Houston Astros", "350", "Houston Astros", "hou", "sports", "465528"),
    ("Kansas City Royals", "351", "Kansas City Royals", "kc", "sports", "465731"),
    ("Los Angeles Angels", "352", "Los Angeles Angels", "laa", "sports", "465642"),
    ("Los Angeles Dodgers", "353", "Los Angeles Dodgers", "lad", "sports", "465761"),
    ("Miami Marlins", "354", "Miami Marlins", "mia", "sports", "465548"),
    ("Milwaukee Brewers", "355", "Milwaukee Brewers", "mil", "sports", "465633"),
    ("Minnesota Twins", "356", "Minnesota Twins", "min", "sports", "465598"),
    ("New York Mets", "357", "New York Mets", "nym", "sports", "465547"),
    ("New York Yankees", "358", "New York Yankees", "nyy", "sports", "465667"),
    ("Oakland Athletics", "359", "Oakland Athletics", "oak", "sports", "465542"),
    ("Philadelphia Phillies", "360", "Philadelphia Phillies", "phi", "sports", "465689"),
    ("Pittsburgh Pirates", "361", "Pittsburgh Pirates", "pit", "sports", "465703"),
    ("San Diego Padres", "362", "San Diego Padres", "sd", "sports", "465795"),
    ("San Francisco Giants", "363", "San Francisco Giants", "sf", "sports", "465773"),
    ("Seattle Mariners", "364", "Seattle Mariners", "sea", "sports", "465605"),
    ("St. Louis Cardinals", "365", "St. Louis Cardinals", "stl", "sports", "465720"),
    ("Tampa Bay Rays", "366", "Tampa Bay Rays", "tb", "sports", "465645"),
    ("Texas Rangers", "367", "Texas Rangers", "tex", "sports", "465751"),
    ("Toronto Blue Jays", "368", "Toronto Blue Jays", "tor", "sports", "465794"),
    # --- Entertainment 4xx ---
    ("TBS", "401", "TBS", "tbs", "entertainment", "465285"),
    ("TNT", "402", "TNT", "tnt", "entertainment", "465114"),
    ("USA Network", "403", "USA Network", "usa", "entertainment", "465006"),
    ("truTV", "404", "truTV", "tru", "entertainment", "464987"),
    ("Travel Channel", "405", "Travel Channel", "trvl", "entertainment", "465186"),
    ("Hallmark", "406", "Hallmark Channel", "hall", "entertainment", "465241"),
    ("Lifetime", "407", "Lifetime", "life", "entertainment", "465290"),
    ("TLC", "408", "TLC", "tlc", "entertainment", "464919"),
    ("BBC", "409", "BBC America", "bbc", "entertainment", "465025"),
    ("BET", "410", "BET", "bet", "entertainment", "464968"),
    ("TV ONE", "411", "TV One", "tvo", "entertainment", "465208"),
    # --- Documentary 45x ---
    ("Discovery Channel", "451", "Discovery Channel", "disc", "documentary", "465364"),
    ("History", "452", "History", "hist", "documentary", "465176"),
    ("National Geographic", "453", "National Geographic", "natg", "documentary", "465089"),
    # --- Kids 5xx ---
    ("Disney Channel", "501", "Disney Channel", "dis", "kids", "465349"),
    ("Nickelodeon TV", "502", "Nickelodeon", "nick", "kids", "465251"),
    ("Universal Kids", "503", "Universal Kids", "unik", "kids", ""),
    # --- Premium 6xx ---
    ("HBO", "601", "HBO", "hbo", "premium", "464745"),
    ("Cinemax", "602", "Cinemax", "cinx", "premium", "464917"),
    ("Showtime", "603", "Showtime", "sho", "premium", ""),
    ("MAX", "604", "MAX", "max", "premium", ""),
    # --- Espanol 7xx ---
    ("Univision", "701", "Univision", "uni", "spanish", "464782"),
    ("Telemundo", "702", "Telemundo", "tld", "spanish", "464962"),
    ("NBC Universo", "703", "Universo", "univ", "spanish", "465329"),
    ("ESPN Deportes", "704", "ESPN Deportes", "espd", "spanish", "464949"),
    ("FOX Deportes", "705", "FOX Deportes", "fde", "spanish", "465156"),
]
