(function () {
  const form = document.getElementById("convert-form");
  const submitBtn = document.getElementById("submit-btn");
  const statusEl = document.getElementById("status");

  function showStatus(text, variant) {
    statusEl.hidden = false;
    statusEl.textContent = text;
    statusEl.className = "status";
    if (variant === "error") statusEl.classList.add("is-error");
    if (variant === "busy") statusEl.classList.add("is-busy");
  }

  function hideStatus() {
    statusEl.hidden = true;
    statusEl.textContent = "";
    statusEl.className = "status";
  }

  function parseErrorDetail(data, fallback) {
    if (typeof data === "object" && data !== null && "detail" in data) {
      const d = data.detail;
      if (typeof d === "string") return d;
      if (Array.isArray(d) && d.length > 0 && d[0].msg) {
        return d.map((e) => e.msg).join(" ");
      }
    }
    return fallback || "Request failed.";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideStatus();

    const fd = new FormData(form);
    const styleFile = fd.get("style_reference");
    const targetFile = fd.get("target_image");
    if (!(styleFile instanceof File) || styleFile.size === 0) {
      showStatus("Choose a style reference image.", "error");
      return;
    }
    if (!(targetFile instanceof File) || targetFile.size === 0) {
      showStatus("Choose a target image.", "error");
      return;
    }
    const prompt = String(fd.get("prompt") || "").trim();
    if (!prompt) {
      showStatus("Enter a prompt with instructions for the transfer.", "error");
      return;
    }

    submitBtn.disabled = true;
    showStatus("Generating styled image and Illustrator file… this can take a minute.", "busy");

    try {
      const res = await fetch("/convert", {
        method: "POST",
        body: fd,
      });

      if (!res.ok) {
        let msg = `${res.status} ${res.statusText}`;
        const ct = res.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          try {
            const json = await res.json();
            msg = parseErrorDetail(json, msg);
          } catch (_) {
            /* keep default */
          }
        } else {
          try {
            const t = await res.text();
            if (t) msg = t.slice(0, 500);
          } catch (_) {
            /* keep default */
          }
        }
        showStatus(msg, "error");
        return;
      }

      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      let filename = "output.ai";
      const m = cd.match(/filename="([^"]+)"/i) || cd.match(/filename=([^;]+)/i);
      if (m) filename = m[1].trim().replace(/^["']|["']$/g, "");

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      showStatus(`Download started (${filename}).`, "busy");
      statusEl.classList.remove("is-busy");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Network error.", "error");
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
