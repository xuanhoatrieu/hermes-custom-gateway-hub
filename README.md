# Hermes Custom Gateway Hub (`custom-gateway-hub` `v1.1.0`)

Unified Plugin (**Backend Python + Giao diện Hermes Desktop**) **100% an toàn khi cập nhật (`hermes update`)**, giúp kết nối tới bất kỳ OpenAI-compatible Custom Gateway / Proxy nào trên **máy mới hoàn toàn mà không cần tự sửa tay file `.env` hay `config.yaml`**.

---

## Điểm mới nổi bật ở bản `v1.1.0` (Zero-Touch Fresh PC)

- **Chuẩn Unified Plugin chính thức của Hermes**: Cài trực tiếp 1 cú nhấp chuột ngay trong **Hermes Desktop (`Capabilities → Plugins → Install`)** hoặc qua lệnh `hermes plugins install xuanhoatrieu/hermes-custom-gateway-hub`.
- **Onboarding tự động trên máy mới**: Khi chưa có `Base URL` hoặc `API Key`, trang **`Gateway Models`** tự động mở khung thiết lập nhanh kèm hướng dẫn 3 bước; dán `Base URL` + `API Key` và bấm **`Check Connection`** là tự lưu khóa bảo mật vào `$HERMES_HOME/.env` và nạp toàn bộ danh sách model.
- **Tự động bật lá chắn chống lỗi tạo ảnh `HTTP 502` qua Proxy**: Công tắc **`Chống lỗi Proxy HTTP 502 khi tạo ảnh (image_generate)`** tự động cấu hình `agent.environment_hint` trên máy mới để ngăn model gọi nhầm hosted `image_generation` gây lỗi `HTTP 502: Complexity 'high' is not supported`.
- **Tự động mở khóa bộ lọc hiển thị model trên Desktop**: Tự dọn các khóa lọc cũ `custom::*` trong `ui-preferences.json` để menu chọn model dưới khung chat luôn hiển thị đầy đủ các model mới tải về.

---

## Tính năng chính

- **Tự động & Chủ động Check Connection (`/v1/models`)**:
  - Tự động kiểm tra và đồng bộ model mới khi mở trang (chu kỳ chống spam 60 giây).
  - Nút **`Check Connection & Tải Model mới`** đo độ trễ (`ms`), hiển thị trạng thái kết nối trực quan và gắn nhãn **`MỚI`** cho các model vừa xuất hiện trên Gateway.
- **Tách riêng 2 bảng chọn Model**:
  - **Model Sinh Nội Dung (Chat / Reasoning)**: Tìm kiếm nhanh, lọc theo họ model (`OpenAI / GPT`, `Anthropic / Claude`, `Google / Gemini`, ...), áp dụng tức thì cho phiên chat đang mở.
  - **Model Tạo Ảnh (Image Generation)**: Đăng ký dynamic provider `custom-gateway` cho công cụ `image_generate` của Hermes, hỗ trợ cả chuẩn `/v1/images/generations` (`gpt-image-*`, `flux-*`, `dall-e-*`) lẫn fallback `/v1/chat/completions` (`gemini-3.1-flash-image`).
- **Đồng bộ đa bề mặt**:
  - Mục điều hướng **`Gateway Models`** ở thanh Sidebar bên trái (`/gateway-hub`).
  - Chip hiển thị nhanh Model Tạo Ảnh đang dùng ở góc phải thanh trạng thái (`StatusBar`).
  - Trang cấu hình trong **Settings → Plugins → Custom Gateway Hub** và lệnh nhanh trong **Command Palette (`Ctrl+K`)**.
  - Tùy chọn tự động đồng bộ biến môi trường tạo ảnh sang skill `ppt-master` (`skills/productivity/ppt-master/.env`).

---

## Cấu trúc Unified Plugin Package (`v1.1.0`)

```text
hermes-custom-gateway-hub/       # Được cài thẳng vào $HERMES_HOME/plugins/custom-gateway-hub/
├── plugin.yaml                  # Manifest backend plugin (v1.1.0)
├── __init__.py                  # CustomGatewayImageProvider (image_gen registry)
├── gateway_core.py              # Bộ lõi /v1/models probe, phân loại model, lưu .env & config.yaml
├── dashboard/
│   ├── manifest.json            # Khai báo hot-mount API cho Hermes Dashboard/Desktop
│   └── plugin_api.py            # FastAPI routes: GET /state, POST /check, POST /apply
├── desktop/
│   └── plugin.js                # Giao diện Hermes Desktop (@hermes/plugin-sdk ESM)
├── config.example.yaml          # Cấu hình tham khảo (không bắt buộc sửa tay)
└── install.ps1                  # Script cài đặt nhanh trên Windows PowerShell
```

---

## Cài đặt trên máy mới (Sử dụng được ngay — Zero Manual Config)

### Cách 1: Cài trực tiếp trong giao diện Hermes Desktop (Khuyên dùng)

1. Mở **Hermes Desktop** → vào **Capabilities → Plugins → Install**.
2. Dán địa chỉ:
   ```text
   xuanhoatrieu/hermes-custom-gateway-hub
   ```
3. Giữ dấu tích **`Enable after install`** → nhấn **Install**.
4. Nhấn vào mục **`Gateway Models`** vừa xuất hiện ở thanh bên trái:
   - Nhập **Base URL** (ví dụ `https://your-gateway.example.com/v1`) và **API Key**.
   - Nhấn **`Check Connection & Tải Model mới`**.
   - Chọn **Model Sinh Nội Dung** + **Model Tạo Ảnh** rồi bấm **`Lưu & Áp dụng ngay`** là dùng được ngay lập tức!

### Cách 2: Cài bằng Hermes CLI

```bash
hermes plugins install xuanhoatrieu/hermes-custom-gateway-hub
```
Sau đó mở **Hermes Desktop → Capabilities → Plugins**, bật công tắc **Custom Gateway Hub**, rồi mở tab **`Gateway Models`** để nhập URL & API Key.

### Cách 3: Cài bằng PowerShell Script (Windows)

```powershell
git clone https://github.com/xuanhoatrieu/hermes-custom-gateway-hub.git
.\hermes-custom-gateway-hub\install.ps1
```
Script sẽ tự chép cả Backend + Desktop UI vào `$HERMES_HOME` và tự động bật `custom-gateway-hub` trong `config.yaml`.

---

## Giấy phép

MIT License.
