<?php
/**
 * Удаляет <img> теги с указанными URL из контента всех постов/страниц.
 * Файлы в медиабиблиотеке НЕ трогаются — только убирается тег из содержимого.
 *
 * Использование:
 *   wp eval-file remove-images.php urls.txt
 *
 * urls.txt — текстовый файл, один URL картинки на строку.
 *
 * По умолчанию делает "сухой прогон" (dry-run) — только показывает, что БУДЕТ изменено,
 * ничего не сохраняет. Чтобы реально применить изменения, добавь слово apply ПОСЛЕ имени файла:
 *   wp eval-file remove-images.php urls.txt apply
 */

$args = $args ?? [];
$assoc_args = $assoc_args ?? [];

if (empty($args[0])) {
    WP_CLI::error("Укажи файл со списком URL: wp eval-file remove-images.php urls.txt");
}

$urls_file = $args[0];
if (!file_exists($urls_file)) {
    WP_CLI::error("Файл не найден: $urls_file");
}

$apply = in_array('apply', $args, true);

$raw_urls = file($urls_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
$target_urls = array_filter(array_map('trim', $raw_urls));

if (empty($target_urls)) {
    WP_CLI::error("Список URL пуст.");
}

// Готовим также "базовые" имена файлов (на случай отличий в протоколе/домене/размере превью)
$target_basenames = [];
foreach ($target_urls as $u) {
    $path = parse_url($u, PHP_URL_PATH);
    if ($path) {
        $target_basenames[] = basename($path);
    }
}
$target_basenames = array_unique($target_basenames);

WP_CLI::log("Целевых URL: " . count($target_urls));
WP_CLI::log("Режим: " . ($apply ? "ПРИМЕНЕНИЕ ИЗМЕНЕНИЙ" : "DRY-RUN (ничего не сохраняется)"));
WP_CLI::log("---");

$posts = get_posts([
    'post_type'      => ['post', 'page'],
    'post_status'    => 'any',
    'numberposts'    => -1,
]);

$total_changed_posts = 0;
$total_removed_images = 0;

foreach ($posts as $post) {
    $content = $post->post_content;
    if (empty($content) || strpos($content, '<img') === false) {
        continue;
    }

    $doc = new DOMDocument();
    libxml_use_internal_errors(true);
    // Оборачиваем в UTF-8 meta, чтобы DOMDocument не портил кириллицу
    $doc->loadHTML('<?xml encoding="UTF-8">' . $content, LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD);
    libxml_clear_errors();

    $imgs = $doc->getElementsByTagName('img');
    $to_remove = [];

    foreach ($imgs as $img) {
        $src = $img->getAttribute('src');
        if (!$src) {
            continue;
        }
        $basename = basename(parse_url($src, PHP_URL_PATH));

        $matched = in_array($src, $target_urls, true) || in_array($basename, $target_basenames, true);

        if ($matched) {
            $to_remove[] = $img;
        }
    }

    if (empty($to_remove)) {
        continue;
    }

    WP_CLI::log("[{$post->post_type} #{$post->ID}] {$post->post_title} — найдено к удалению: " . count($to_remove));
    foreach ($to_remove as $img) {
        WP_CLI::log("    - " . $img->getAttribute('src'));
    }

    if ($apply) {
        foreach ($to_remove as $img) {
            $img->parentNode->removeChild($img);
        }
        $new_content = $doc->saveHTML();
        // Убираем обёртку, которую DOMDocument мог добавить
        $new_content = preg_replace('/^<\?xml encoding="UTF-8">/', '', $new_content);

        wp_update_post([
            'ID'           => $post->ID,
            'post_content' => $new_content,
        ]);
    }

    $total_changed_posts++;
    $total_removed_images += count($to_remove);
}

// --- Проверка featured image (миниатюр записей) ---
WP_CLI::log("---");
WP_CLI::log("Проверка миниатюр (featured images)...");

$thumb_matches = 0;

foreach ($posts as $post) {
    $thumb_id = get_post_thumbnail_id($post->ID);
    if (!$thumb_id) {
        continue;
    }
    $thumb_url = wp_get_attachment_url($thumb_id);
    if (!$thumb_url) {
        continue;
    }
    $basename = basename(parse_url($thumb_url, PHP_URL_PATH));

    $matched = in_array($thumb_url, $target_urls, true) || in_array($basename, $target_basenames, true);

    if ($matched) {
        $thumb_matches++;
        WP_CLI::log("[{$post->post_type} #{$post->ID}] {$post->post_title} — миниатюра совпадает: {$thumb_url}");
        if ($apply) {
            delete_post_thumbnail($post->ID);
        }
    }
}

WP_CLI::log("---");
WP_CLI::success("Затронуто постов/страниц (контент): {$total_changed_posts}. Удалено бы тегов <img>: {$total_removed_images}. "
    . "Совпавших миниатюр: {$thumb_matches}."
    . ($apply ? " Изменения сохранены." : " Это был dry-run — ничего не сохранено, добавь --apply для реального применения."));
