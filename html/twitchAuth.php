<?php
if (array_key_exists('code', $_GET)) {
    echo "Paste this code in the application: " . $_GET['code'] . "\n";
}
else {
    echo 'nope';
}
?>
