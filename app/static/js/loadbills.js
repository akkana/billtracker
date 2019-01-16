/* Load bills as they come in, until they're all there */

//(function() {

  // https://javascript.info/xmlhttprequest
  var ajax_get = function(url, callback) {
      console.log("Making AJAX request");

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
              console.log(xhr.status + ': ' + xhr.statusText);
          } else {
              // responseText is the server response
              //console.log("Received data: " + xhr.responseText);
              callback(JSON.parse(xhr.responseText));
          }
      }
    };

    // Another option: https://developer.mozilla.org/en-US/docs/Learn/JavaScript/Client-side_web_APIs/Fetching_data

    var url = "/api/onebill"

    var display_result = function(data) {
        console.log(data);
        console.log("display_result: data = " + data + ", type " + typeof(data));
        console.log("'summary' is: " + data['summary']);
        console.log("'more' is: " + data['more']);

        var billsum = document.getElementById('bill_summary');

        more = data["more"];
        if (data["summary"]) {
            billsum.innerHTML += data["summary"];
        }
        else {
            billsum.innerHTML += data;
        }
        if (data["more"]) {
            console.log("Looping");
            ajax_get(url, display_result);
        }
        else {
            console.log("Done");
            billsum.innerHTML += "<br />Done";
        }
    };

    window.onload = function () {
        // console.log isn't useful, doesn't get called
        console.log("onload function");

        display_result("Please wait ...");

        console.log("Calling ajax_get from onload");
        ajax_get(url, display_result);
    }
//})();

