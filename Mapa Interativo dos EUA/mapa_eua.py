from __future__ import annotations

import io
import json
import shutil
import webbrowser
import zipfile
from pathlib import Path

import folium
import pandas as pd
import requests
import shapefile  # biblioteca pyshp


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Vintage mais recente utilizado neste projeto.
# Em setembro de 2026, o Census Bureau disponibiliza
# as estimativas estaduais completas mais recentes no Vintage 2025.
POPULATION_VINTAGE = 2025

BASE_DIR = Path(__file__).resolve().parent

CACHE_DIR = BASE_DIR / "cache"

MAP_FILE = BASE_DIR / "mapa_estados_eua.html"


# ============================================================
# FONTES OFICIAIS DO U.S. CENSUS BUREAU
# ============================================================

# Limites geográficos oficiais dos estados.
#
# Arquivo:
# cb_2025_us_state_500k.zip
#
# 1:500.000 - escala nacional
#
BOUNDARY_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2025/shp/"
    "cb_2025_us_state_500k.zip"
)


# Arquivo oficial de estimativas de população.
#
# O programa usa a coluna:
# POPESTIMATE2025
#
POPULATION_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2025/state/totals/NST-EST2025-ALLDATA.csv"
)


# ============================================================
# CÓDIGOS FIPS DOS 50 ESTADOS + DISTRITO DE COLUMBIA
# ============================================================

VALID_FIPS = {
    "01",  # Alabama
    "02",  # Alaska
    "04",  # Arizona
    "05",  # Arkansas
    "06",  # California
    "08",  # Colorado
    "09",  # Connecticut
    "10",  # Delaware
    "11",  # District of Columbia
    "12",  # Florida
    "13",  # Georgia
    "15",  # Hawaii
    "16",  # Idaho
    "17",  # Illinois
    "18",  # Indiana
    "19",  # Iowa
    "20",  # Kansas
    "21",  # Kentucky
    "22",  # Louisiana
    "23",  # Maine
    "24",  # Maryland
    "25",  # Massachusetts
    "26",  # Michigan
    "27",  # Minnesota
    "28",  # Mississippi
    "29",  # Missouri
    "30",  # Montana
    "31",  # Nebraska
    "32",  # Nevada
    "33",  # New Hampshire
    "34",  # New Jersey
    "35",  # New Mexico
    "36",  # New York
    "37",  # North Carolina
    "38",  # North Dakota
    "39",  # Ohio
    "40",  # Oklahoma
    "41",  # Oregon
    "42",  # Pennsylvania
    "44",  # Rhode Island
    "45",  # South Carolina
    "46",  # South Dakota
    "47",  # Tennessee
    "48",  # Texas
    "49",  # Utah
    "50",  # Vermont
    "51",  # Virginia
    "53",  # Washington
    "54",  # West Virginia
    "55",  # Wisconsin
    "56",  # Wyoming
}


# ============================================================
# DOWNLOAD
# ============================================================

def download_file(
    url: str,
    destination: Path,
    description: str
) -> None:
    """
    Faz o download de um arquivo da internet.
    """

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    print()
    print(f"Baixando {description}...")
    print(f"URL: {url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Python; mapa interativo dos estados dos EUA)"
        )
    }

    try:

        with requests.get(
            url,
            headers=headers,
            timeout=60,
            stream=True
        ) as response:

            response.raise_for_status()

            with destination.open("wb") as file:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:
                        file.write(chunk)

    except requests.RequestException as exc:

        raise RuntimeError(
            "Não foi possível acessar os dados oficiais "
            "do U.S. Census Bureau.\n\n"
            "Verifique a conexão com a internet e tente novamente."
        ) from exc

    print(f"Arquivo salvo em:")
    print(destination)


# ============================================================
# OBTÉM O SHAPEFILE OFICIAL
# ============================================================

def get_boundary_shapefile() -> Path:
    """
    Baixa e extrai o shapefile oficial dos estados.
    """

    states_dir = CACHE_DIR / "states"

    # Se já existe um shapefile extraído,
    # não precisamos baixar novamente.
    shp_candidates = list(
        states_dir.glob("*.shp")
    )

    if shp_candidates:
        return shp_candidates[0]

    zip_path = (
        CACHE_DIR /
        "cb_2025_us_state_500k.zip"
    )

    download_file(
        BOUNDARY_URL,
        zip_path,
        "os limites geográficos oficiais dos estados"
    )

    # Apaga uma extração antiga incompleta.
    if states_dir.exists():
        shutil.rmtree(states_dir)

    states_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    try:

        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as archive:

            archive.extractall(states_dir)

    except zipfile.BadZipFile as exc:

        raise RuntimeError(
            "O arquivo de limites baixado não é um ZIP válido."
        ) from exc

    shp_candidates = list(
        states_dir.glob("*.shp")
    )

    if not shp_candidates:

        raise RuntimeError(
            "O ZIP do Census Bureau foi baixado, "
            "mas nenhum shapefile foi encontrado."
        )

    return shp_candidates[0]


# ============================================================
# POPULAÇÃO
# ============================================================

def load_population_data() -> dict:
    """
    Baixa a tabela de população do Census Bureau
    e monta um dicionário indexado pelo FIPS.
    """

    print()
    print(
        "Atualizando os dados de população "
        "pela internet..."
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Python; mapa interativo dos estados dos EUA)"
        )
    }

    try:

        response = requests.get(
            POPULATION_URL,
            headers=headers,
            timeout=60
        )

        response.raise_for_status()

    except requests.RequestException as exc:

        raise RuntimeError(
            "Não foi possível baixar a população "
            "oficial do U.S. Census Bureau."
        ) from exc

    try:

        dataframe = pd.read_csv(
            io.BytesIO(response.content),
            dtype={
                "STATE": "string"
            }
        )

    except Exception as exc:

        raise RuntimeError(
            "O arquivo CSV de população do "
            "Census Bureau não pôde ser lido."
        ) from exc

    # --------------------------------------------------------
    # Verificação das colunas esperadas
    # --------------------------------------------------------

    population_column = (
        f"POPESTIMATE{POPULATION_VINTAGE}"
    )

    required_columns = {
        "SUMLEV",
        "STATE",
        "NAME",
        population_column
    }

    missing_columns = (
        required_columns -
        set(dataframe.columns)
    )

    if missing_columns:

        raise RuntimeError(
            "O arquivo do Census Bureau mudou de estrutura "
            "e está sem as colunas:\n"
            +
            "\n".join(
                sorted(missing_columns)
            )
        )

    # --------------------------------------------------------
    # Normalização
    # --------------------------------------------------------

    dataframe["SUMLEV"] = pd.to_numeric(
        dataframe["SUMLEV"],
        errors="coerce"
    )

    dataframe["STATE"] = (
        dataframe["STATE"]
        .astype("string")
        .str.zfill(2)
    )

    # --------------------------------------------------------
    # SUMLEV = 40
    #
    # corresponde aos estados/equivalentes estaduais
    # no arquivo de Population Estimates.
    # --------------------------------------------------------

    states = dataframe[
        (dataframe["SUMLEV"] == 40)
        &
        dataframe["STATE"].isin(VALID_FIPS)
    ].copy()

    states[population_column] = pd.to_numeric(
        states[population_column],
        errors="coerce"
    )

    result = {}

    for _, row in states.iterrows():

        fips = str(
            row["STATE"]
        ).zfill(2)

        population = (
            row[population_column]
        )

        if pd.isna(population):
            continue

        result[fips] = {
            "population": int(
                population
            ),

            "census_name": str(
                row["NAME"]
            )
        }

    # 50 estados + Washington, D.C.
    if len(result) != 51:

        raise RuntimeError(
            f"Foram encontrados {len(result)} "
            "estados/distrito com população.\n\n"
            "O esperado é 51:\n"
            "50 estados + Distrito de Columbia."
        )

    print(
        f"{len(result)} áreas carregadas "
        f"com população do Vintage {POPULATION_VINTAGE}."
    )

    return result


# ============================================================
# CRIA O GEOJSON
# ============================================================

def build_geojson(
    shapefile_path: Path,
    population: dict
) -> dict:
    """
    Converte o shapefile para GeoJSON e acrescenta:
    - nome
    - sigla
    - população
    - código FIPS
    """

    reader = shapefile.Reader(
        str(shapefile_path),
        encoding="utf-8"
    )

    field_names = [
        field[0]
        for field in reader.fields[1:]
    ]

    required_shape_fields = {
        "GEOID",
        "STUSPS",
        "NAME"
    }

    missing = (
        required_shape_fields -
        set(field_names)
    )

    if missing:

        raise RuntimeError(
            "O shapefile do Census Bureau não possui "
            "os campos esperados:\n"
            +
            "\n".join(
                sorted(missing)
            )
        )

    features = []

    for shape_record in reader.iterShapeRecords():

        attributes = dict(
            zip(
                field_names,
                shape_record.record
            )
        )

        fips = str(
            attributes["GEOID"]
        ).zfill(2)

        # Ignora Puerto Rico e outros territórios.
        if fips not in VALID_FIPS:
            continue

        population_info = (
            population.get(fips)
        )

        if population_info is None:
            continue

        state_name = str(
            attributes["NAME"]
        )

        abbreviation = str(
            attributes["STUSPS"]
        )

        population_value = int(
            population_info["population"]
        )

        features.append(
            {
                "type": "Feature",

                "geometry":
                    shape_record
                    .shape
                    .__geo_interface__,

                "properties": {

                    "name":
                        state_name,

                    "abbr":
                        abbreviation,

                    "population":
                        population_value,

                    "population_text":
                        f"{population_value:,}",

                    "fips":
                        fips
                }
            }
        )

    if len(features) != 51:

        raise RuntimeError(
            f"O mapa geográfico retornou "
            f"{len(features)} áreas.\n\n"
            "O esperado é 51 "
            "(50 estados + Distrito de Columbia)."
        )

    print(
        "Geometria dos 50 estados + "
        "Distrito de Columbia carregada."
    )

    return {
        "type": "FeatureCollection",
        "features": features
    }


# ============================================================
# CORES
# ============================================================

def population_color(
    population: int
) -> str:
    """
    Escolhe uma cor com base na população.
    """

    if population >= 20_000_000:
        return "#e63946"

    if population >= 10_000_000:
        return "#f3722c"

    if population >= 5_000_000:
        return "#f9c74f"

    if population >= 2_000_000:
        return "#90be6d"

    if population >= 1_000_000:
        return "#43aa8b"

    return "#577590"


def style_function(
    feature: dict
) -> dict:

    population = int(
        feature["properties"]["population"]
    )

    return {
        "fillColor":
            population_color(
                population
            ),

        "color":
            "#1f2937",

        "weight":
            1.1,

        "fillOpacity":
            0.78
    }


def highlight_function(
    _feature: dict
) -> dict:

    return {
        "weight":
            2.6,

        "color":
            "#111827",

        "fillOpacity":
            0.95
    }


# ============================================================
# CRIA O MAPA
# ============================================================

def create_map(
    geojson_data: dict
) -> folium.Map:

    mapa = folium.Map(

        location=[
            39.0,
            -98.5
        ],

        zoom_start=4,

        tiles="CartoDB positron",

        control_scale=True,

        prefer_canvas=True
    )

    # --------------------------------------------------------
    # PAINEL INFORMATIVO
    # --------------------------------------------------------

    info_html = f"""
    <div style="
        position: fixed;

        top: 14px;
        left: 55px;

        z-index: 9999;

        background:
            rgba(255,255,255,0.96);

        border:
            2px solid #1f2937;

        border-radius:
            12px;

        padding:
            12px 16px;

        box-shadow:
            0 3px 12px
            rgba(0,0,0,0.18);

        font-family:
            Arial, sans-serif;

        line-height:
            1.35;
    ">

        <div style="
            font-size: 18px;
            font-weight: 700;
            color: #111827;
        ">
            Estados Unidos da América
        </div>

        <div style="
            font-size: 12px;
            color: #374151;
            margin-top: 4px;
        ">
            Passe o mouse sobre um estado
            para ver seus dados.
        </div>

        <div style="
            font-size: 11px;
            color: #6b7280;
            margin-top: 6px;
        ">
            População:
            U.S. Census Bureau —
            Vintage {POPULATION_VINTAGE}
        </div>

    </div>
    """

    mapa.get_root().html.add_child(
        folium.Element(info_html)
    )

    # --------------------------------------------------------
    # CAMADA DOS ESTADOS
    # --------------------------------------------------------

    folium.GeoJson(

        data=geojson_data,

        name=(
            "Estados e "
            "Distrito de Columbia"
        ),

        style_function=
            style_function,

        highlight_function=
            highlight_function,

        tooltip=
            folium.GeoJsonTooltip(

                fields=[
                    "name",
                    "abbr",
                    "population_text"
                ],

                aliases=[

                    "Estado / Distrito",

                    "Sigla",

                    (
                        "População estimada "
                        f"({POPULATION_VINTAGE})"
                    )
                ],

                labels=True,

                sticky=True,

                style=(
                    "background-color: white;"
                    "color: #111827;"
                    "font-family: Arial;"
                    "font-size: 13px;"
                    "padding: 8px;"
                )
            )

    ).add_to(mapa)

    # --------------------------------------------------------
    # CONTROLE DE CAMADAS
    # --------------------------------------------------------

    folium.LayerControl(
        collapsed=False
    ).add_to(mapa)

    # --------------------------------------------------------
    # ENQUADRAMENTO INICIAL
    #
    # Inclui:
    # - Alaska
    # - Hawaii
    # - 48 estados contíguos
    # - Washington, D.C.
    # --------------------------------------------------------

    mapa.fit_bounds(
        [
            [
                18.0,
                -179.5
            ],
            [
                72.0,
                -66.0
            ]
        ]
    )

    return mapa


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    try:

        print()
        print("=" * 72)
        print(
            "MAPA INTERATIVO DOS ESTADOS "
            "DOS ESTADOS UNIDOS"
        )
        print(
            "50 estados + Distrito de Columbia"
        )
        print("=" * 72)

        # ----------------------------------------------------
        # 1. População pela internet
        # ----------------------------------------------------

        population = (
            load_population_data()
        )

        # ----------------------------------------------------
        # 2. Limites geográficos oficiais
        # ----------------------------------------------------

        shapefile_path = (
            get_boundary_shapefile()
        )

        # ----------------------------------------------------
        # 3. Criação do GeoJSON
        # ----------------------------------------------------

        geojson_data = (
            build_geojson(
                shapefile_path,
                population
            )
        )

        # ----------------------------------------------------
        # 4. Criação do mapa
        # ----------------------------------------------------

        mapa = create_map(
            geojson_data
        )

        # ----------------------------------------------------
        # 5. Salva o HTML
        # ----------------------------------------------------

        mapa.save(
            str(MAP_FILE)
        )

        print()
        print(
            "Mapa criado com sucesso!"
        )

        print(
            f"Arquivo: {MAP_FILE}"
        )

        # ----------------------------------------------------
        # 6. Abre no navegador
        # ----------------------------------------------------

        print(
            "Abrindo o mapa no navegador..."
        )

        webbrowser.open(
            MAP_FILE
            .resolve()
            .as_uri()
        )

        print()
        print(
            "Programa finalizado."
        )

    except Exception as exc:

        print()
        print("=" * 72)
        print("ERRO")
        print("=" * 72)

        print(exc)

        print()
        print(
            "Verifique:"
        )

        print(
            "1. conexão com a internet;"
        )

        print(
            "2. instalação das bibliotecas;"
        )

        print(
            "3. se o endereço do Census Bureau "
            "está acessível pelo computador."
        )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()