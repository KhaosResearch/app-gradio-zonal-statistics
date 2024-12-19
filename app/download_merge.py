import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from minio import Minio
from minio.error import S3Error
from rasterio.merge import merge
import rasterio

def download_tif_file(client, bucket_name, obj, download_dir):
    original_file_name = obj.object_name.split('/')[-1]
    unique_file_name = f"{obj.object_name.split('/')[0]}_{original_file_name}"
    local_file_path = os.path.join(download_dir, unique_file_name)

    if not os.path.exists(local_file_path):
        client.fget_object(bucket_name, obj.object_name, local_file_path)
    return local_file_path

def parallel_download(client, bucket_name, download_tasks):
    downloaded_files = []
    print("TASKS")
    print(download_tasks)
    print("TASKS")

    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(download_tif_file, client, bucket_name, obj, download_dir)
            for obj, download_dir in download_tasks
        ]
        for future in futures:
            try:
                downloaded_files.append(future.result())
            except Exception as e:
                print(f"Error descargando archivo: {e}")
    print("ARCHIVOS DESCARGADOS")
    print(downloaded_files)
    print("ARCHIVOS DESCARGADOS")
    return downloaded_files

def get_months_for_year(year, start_year, start_month, end_year, end_month):
    """
    Devuelve una lista de meses a descargar para un año específico, considerando el rango de años y meses.
    """
    all_months = ["January", "February", "March", "April", "May", "June", 
                  "July", "August", "September", "October", "November", "December"]

    if year == start_year and year == end_year:  # Mismo año
        start_index = all_months.index(start_month)
        end_index = all_months.index(end_month) + 1
        return all_months[start_index:end_index]
    elif year == start_year:  # Año inicial
        start_index = all_months.index(start_month)
        return all_months[start_index:]
    elif year == end_year:  # Año final
        end_index = all_months.index(end_month) + 1
        return all_months[:end_index]
    else:  # Años intermedios
        return all_months

def download_tif_files(utm_zones, years, indexes, months):
    """
    Descarga imágenes TIFF desde MinIO, las organiza por año, índice y mes,
    y opcionalmente fusiona las imágenes de cada mes en un único archivo.

    Args:
        utm_zones (list): Lista de zonas UTM.
        years (list): Lista de años a descargar.
        indexes (list): Lista de índices (como NDVI, NDWI) a incluir.
        months (list): Lista con el mes inicial y final (e.g., ["March", "June"]).

    Returns:
        list: Lista de rutas de las imágenes TIFF fusionadas.
    """
    print(utm_zones)
    print(years)
    print(indexes)
    print(months)
    local_download_path = tempfile.mkdtemp()
    bucket_name = "test-am-products"
    tiff_paths = []

    client = Minio(
        "192.168.212.101:9000",
        access_key="data-spaces-root",
        secret_key="U|4f36.Vv*]{U&jS",
        secure=False
    )

    download_tasks = []  # Lista de tareas de descarga para paralelizar
    for zone in utm_zones:
        for year in range(int(years[0]), int(years[1]) + 1):
            applicable_months = get_months_for_year(str(year), years[0], months[0], years[1], months[1])
            for month_folder in applicable_months:
                composites_path = f"{zone}/{year}/{month_folder}/composites/"
                try:
                    objects = client.list_objects(bucket_name, prefix=composites_path, recursive=True)
                    for obj in objects:
                        if obj.object_name.endswith(".tif") and "indexes" in obj.object_name:
                            file_parts = obj.object_name.split("/")
                            index_name = file_parts[-1].split(".")[0].upper()
                            if index_name in indexes:
                                month_number = convertir_mes_a_numero(month_folder)
                                download_dir = os.path.join(local_download_path, str(year), index_name, str(month_number))
                                os.makedirs(download_dir, exist_ok=True)
                                download_tasks.append((obj, download_dir))
                except S3Error as exc:
                    print(f"Error al acceder a {composites_path}: {exc}")

    # Descarga paralela
    parallel_download(client, bucket_name, download_tasks)

    # Fusión de imágenes TIFF por mes dentro del rango especificado
    for year in range(int(years[0]), int(years[1]) + 1):
        applicable_months = get_months_for_year(str(year), years[0], months[0], years[1], months[1])
        for index in indexes:
            for month in applicable_months:
                month_number = convertir_mes_a_numero(month)
                carpeta_mes = os.path.join(local_download_path, str(year), index, month_number)
                if os.path.exists(carpeta_mes):
                    merge_path = os.path.join(carpeta_mes, f"{index}_{year}_{month_number}.tif")
                    if merge_tifs(carpeta_mes, merge_path):
                        tiff_paths.append(merge_path)

    return tiff_paths

def merge_tifs(carpeta_entrada, salida_path):
    """
    Fusiona archivos TIFF en una carpeta en un único archivo TIFF.
    """
    imagenes_tif = [os.path.join(carpeta_entrada, f) for f in os.listdir(carpeta_entrada) if f.endswith('.tif')]
    print("imagenes_unir")
    print(imagenes_tif)
    print("imagenes_unir")
    if not imagenes_tif:
        print(f"No se encontraron imágenes TIFF en la carpeta: {carpeta_entrada}")
        return False

    datasets = [rasterio.open(imagen) for imagen in imagenes_tif]
    merged, output_transform = merge(datasets, method="last")

    perfil = datasets[0].profile
    perfil.update(
        driver='GTiff',
        height=merged.shape[1],
        width=merged.shape[2],
        transform=output_transform,
        count=datasets[0].count,
        dtype=merged.dtype
    )
    print("merged:", salida_path)
    with rasterio.open(salida_path, 'w', **perfil) as dst:
        dst.write(merged)

    for ds in datasets:
        ds.close()

    return True

def convertir_mes_a_numero(mes):
    """
    Convierte el nombre del mes en inglés a su número correspondiente.
    """
    meses = {
        "January": "01", "February": "02", "March": "03", "April": "04", "May": "05",
        "June": "06", "July": "07", "August": "08", "September": "09", "October": "10",
        "November": "11", "December": "12"
    }
    return meses.get(mes, 0)
