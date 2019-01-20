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
var even_changed = true;
var even_unchanged = true;

var display_result = function(data) {
    //console.log(data);

    if (data["summary"]) {
        text = data["summary"];

        // If the bill has changed, insert it in the changed table
        // as a td inside a tr with class evenodd:

        if (data["changed"]) {

            var changedbilltable = document.getElementById('changed_bills')
                .getElementsByTagName('tbody')[0];

            billtable = changedbilltable;
            even_changed = !even_changed;
            even = even_changed;

            if (even)
                evenodd = "even";
            else
                evenodd = "odd";

            // Insert a row in the table at the last row
            var newRow   = billtable.insertRow(billtable.rows.length);
            newRow.classList.add(evenodd);
            newRow.id = "ch_" + data["billno"];

            // Insert a cell in the row at index 0
            var newCell  = newRow.insertCell(0);

            newCell.innerHTML = text;

            var oldline = document.getElementById(data["billno"]);
            if (oldline) {
                oldline.parentNode.removeChild(oldline);
            }
        }

        // Is this the last bill?
        if (data["more"]) {
            console.log("That was " + data["billno"] + ", but there's more");
            ajax_get(url, display_result);
        }
        else {
            // Done: clear busy indicator.
            console.log("That's all, folks");
            var busywait = document.getElementById("busywait");
            if (busywait) {
                busywait.parentNode.removeChild(busywait);
            }
            else {
                console.log("Can't get busywait");
            }
        }
    }
    /*
    else {
        // It's text. Show it in the busy indicator area.
        document.getElementById('busywait').innerHTML = data;
    }
    */
};

window.onload = function () {
    display_result("Updating, please wait ...");

    ajax_get(url, display_result);
}

