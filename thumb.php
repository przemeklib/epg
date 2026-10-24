<?php
/**
 * Dynamic Image Resizer - Obsługa PNG Transparent & High Quality
 * WAŻNE !!! UTWÓRZ I NADAJ UPRAWNIENIA SERWERA WWW FOLDEROWI cache
 */

//$allowed_domains = ['ptv-prod.wpcdn.pl', 'wpcdn.pl', 'epg.ovh', 'static.epg.ovh'];
$allowed_domains = [
    'wpcdn.pl',
    'epg.ovh',
    'tvp.pl',
    'teleman.pl',
    'sweet.tv',
    'wphcdn.cloud',
    'lulzy.eu',
    'vantagetv.eu',
    'rakuten.tv',
    'gstatic.com',
    'cloud.ovh.net'
];

$cache_dir = 'cache/';
if (isset($_GET['amp;src'])) {
    $_GET['src'] = $_GET['amp;src'];
}

$source_url = $_GET['src'] ?? null;
$width = isset($_GET['w']) ? (int)$_GET['w'] : null;
$height = isset($_GET['h']) ? (int)$_GET['h'] : null;

if (!$source_url) die("Brak parametru src.");

$host = parse_url($source_url, PHP_URL_HOST);
$is_allowed = false;

foreach ($allowed_domains as $domain) {
    // Sprawdza czy host to dokładnie domena LUB czy kończy się na .domena
    if ($host === $domain || str_ends_with($host, '.' . $domain)) {
        $is_allowed = true;
        break;
    }
}

if (!$is_allowed) {
    if (file_exists('no_auth.png')) {
        header('Content-Type: image/png');
        readfile('no_auth.png');
        exit;
    } else {
        // Zabezpieczenie w przypadku braku pliku no_auth.png na serwerze
        header("HTTP/1.1 403 Forbidden");
        die("Domena $host nie jest dozwolona.");
    }
}

// Rozpoznawanie rozszerzenia dla cache
$path_info = pathinfo(parse_url($source_url, PHP_URL_PATH));
$extension = isset($path_info['extension']) ? strtolower($path_info['extension']) : 'jpg';
if (!in_array($extension, ['jpg', 'jpeg', 'png', 'gif'])) $extension = 'jpg';

$cache_key = md5($source_url . $width . $height);
$cache_file = $cache_dir . $cache_key . "." . $extension;

if (file_exists($cache_file)) {
    $mime = ($extension === 'png') ? 'image/png' : 'image/jpeg';
    header("Content-Type: $mime");
    readfile($cache_file);
    exit;
}

// Pobieranie obrazu
$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, $source_url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, 1);
$image_data = curl_exec($ch);
curl_close($ch);

$src_img = imagecreatefromstring($image_data);
if (!$src_img) die("Błędny obraz.");

$orig_w = imagesx($src_img);
$orig_h = imagesy($src_img);

// Obliczanie wymiarów
if ($height) {
    $new_h = $height;
    $new_w = floor($orig_w * ($new_h / $orig_h));
} else {
    $new_w = $width ?: $orig_w;
    $new_h = floor($orig_h * ($new_w / $orig_w));
}

$dst_img = imagecreatetruecolor($new_w, $new_h);

// --- KLUCZOWA ZMIANA: OBSŁUGA PRZEZROCZYSTOŚCI ---
if ($extension === 'png' || $extension === 'gif') {
    imagealphablending($dst_img, false);
    imagesavealpha($dst_img, true);
    $transparent = imagecolorallocatealpha($dst_img, 255, 255, 255, 127);
    imagefill($dst_img, 0, 0, $transparent);
}

imagecopyresampled($dst_img, $src_img, 0, 0, 0, 0, $new_w, $new_h, $orig_w, $orig_h);

// Wysyłka i zapis w zależności od formatu
if ($extension === 'png') {
    header('Content-Type: image/png');
    imagepng($dst_img, $cache_file, 9); // Kompresja PNG (0-9, 9 to max kompresja bezstratna)
    imagepng($dst_img);
} else {
    header('Content-Type: image/jpeg');
    imagejpeg($dst_img, $cache_file, 90);
    imagejpeg($dst_img, null, 90);
}

imagedestroy($src_img);
imagedestroy($dst_img);
