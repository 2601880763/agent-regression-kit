import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class DemoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/chat":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(
            self.rfile.read(length).decode("utf-8")
        )

        # 固定演示输入，不实现模型推理。
        if request.get("input") != "查询工单DEMO-001":
            self.send_error(400, "Unsupported demo input")
            return

        payload = {
            "success": True,
            "data": {
                "answer": "演示工单DEMO-001当前为OPEN。",
                "calls": [
                    {
                        "toolName": "get_ticket",
                        "arguments": {
                            "ticket_id": "DEMO-001"
                        },
                        "argumentsTruncated": False,
                        "outcome": "SUCCEEDED",
                    }
                ],
                "truncated": False,
            },
        }

        body = json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type", "application/json; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("模拟JSON服务：http://127.0.0.1:8099/chat")
    HTTPServer(("127.0.0.1", 8099), DemoHandler).serve_forever()