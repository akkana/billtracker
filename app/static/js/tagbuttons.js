     // checkbox_clicked is called whenever one of the checkboxes inside
     // the modal dialog is called, to give visual indications of what
     // changed and the need to click the Update button.
      function checkbox_clicked(checkbox) {
        // First find the table row for this bill, outside the checkbox dialog
        var tr = checkbox;
        while (tr.nodeName != 'TR') {
          if (tr.nodeName == 'BODY') {
            console.log("checkbox_clicked(): Couldn't find parent tr");
            return;
          }
          tr = tr.parentElement;
        }
        /* Change all tr children's (td's) backgrounds to light red */
        for (child of tr.children)
          child.style.background = '#fcc';

        /* Highlight the need to click Update */
        for (p of document.getElementsByClassName("no-changes-until-click")) {
          p.style.background = '#fcc';
          for (btn of p.getElementsByClassName("update-tags-submit")) {
            btn.classList.add("update-tags-submit-modified");
          }
        }

        /* Adjust the display of which tags are set */
        // First, get the state of checkbox and its siblings
        var modal_body = checkbox;
        while (modal_body.className != 'modal-body') {
          if (modal_body.nodeName == 'BODY') {
            console.log("checkbox_clicked(): Couldn't find modal-body");
            return;
          }
          modal_body = modal_body.parentElement;
        }

        var colortag_holder = tr.getElementsByClassName("colortag-holder")[0];
        if (! colortag_holder) {
          console.log("Couldn't find colortag_holder");
          return;
        }

        // The checkbox has an id of something like "HJR1-privacy-id"
        var checkboxTag = checkbox.id.split('-')[1];
        if (checkbox.checked) {
          /* Add a colortag for a newly toggled button */
          console.log("Will add", checkboxTag);
          var span = document.createElement("span");
          span.textContent = checkboxTag;
          //span.innerHTML = checkboxTag;
          span.className = "colortag";
          span.style.background = "blue";
          span.style.color = "yellow";
          colortag_holder.appendChild(span);
        }
        else {
        /* Remove colortags for un-toggled buttons */
          for (tag of colortag_holder.getElementsByClassName("colortag")) {
            var tagname = tag.textContent;
            if (tagname == checkboxTag) {
            console.log("Will remove", tag);
              tag.remove();
            }
          }
        }
      }
