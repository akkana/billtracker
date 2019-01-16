/* Load bills as they come in, until they're all there */

var ajax_get = function(url, callback) {
    // 1. Create a new XMLHttpRequest object
    let xhr = new XMLHttpRequest();

    // 2. Configure it: GET-request for the URL /article/.../hello.txt
    xhr.open('GET', url);

    // 3. Send the request over the network
    xhr.send();

    // 4. This will be called after the response is received
    xhr.onload = function() {
        if (xhr.status != 200) { // analyze HTTP status of the response
            // if it's not 200, consider it an error
            // e.g. 404: Not Found
            callback(xhr.status + ': ' + xhr.statusText);
            //console.log(xhr.status + ': ' + xhr.statusText);
        } else {
            // responseText is the server response
            //console.log("Received data: " + xhr.responseText);
            callback(JSON.parse(xhr.responseText));
        }
    }
};

var url = "/api/onebill/" + current_user;
var even = true;

var display_result = function(data) {
    //console.log(data);

    var billtable = document.getElementById('bill_list').getElementsByTagName('tbody')[0];

    even = !even;
    if (even)
        evenodd = "even";
    else
        evenodd = "odd";

    if (data["summary"]) {
        text = data["summary"];

        // Now insert text as a td inside a tr with class evenodd.

        // Insert a row in the table at the last row
        var newRow   = billtable.insertRow(billtable.rows.length);
        newRow.classList.add(evenodd);

        // Insert a cell in the row at index 0
        var newCell  = newRow.insertCell(0);

        newCell.innerHTML = text;

        if (data["more"]) {
            ajax_get(url, display_result);
        }
        else {
            // Done: clear busy indicator.
            document.getElementById('busybusy').innerHTML = '';
        }
    }
    else {
        // It's text. Show it in the busy indicator area.
        document.getElementById('busybusy').innerHTML = data;
    }
};

window.onload = function () {
    display_result("Updating, please wait ...");

    ajax_get(url, display_result);
}

