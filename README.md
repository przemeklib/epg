merge_epg.py - łączy kilka źródeł EPG w jeden plik

sources.txt - pliki źródłowe EPG (plik lokalny lub URL xml lub gz)

epg.py - modyfikuje wynikowy EPG (przycina zakres dni, sortuje i usuwa kanały, przepuszcza logo stacji TV i obraz programu przez skrypt zmniejszając rozmiary i wagę)

order_channels.txt - sortuje kanały po <channel id=""> - przydatne jeśli twój klient IPTV tak układa kolejność stacji w menu

remove_channels.txt - usuwa nadmiarowe kanały

thumb.php - zmniejsza rozmiary grafik podawane przez EPG (logo TV, screen programu) do wymiarów podanych w epg.py, przydatne kiedy twój hardware nie jest wydajny (GPU RAM, CPU,
            mało pamięci masowej na cache), dodatkowo na serwerze www jest zapisywany cache tej grafiki. Rozmiar grafik zmniejszony do 90%. Obsługuje tylko autoryzowane domeny.
