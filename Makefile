PYTHON_SRCS= \
	miner_exporter.py \
	miner_jsonrpc.py

PYTHON?= python3

DESTROOT?= /home/helium/validator_exporter

BUILT_SERVICE= build/validator_exporter.service
STARTUP= build/run

all: $(BUILT_SERVICE) $(STARTUP)

install: $(DESTROOT)/pyenv $(STARTUP)
	for pysrc in $(PYTHON_SRCS); do \
		install -D $$pysrc $(DESTROOT); \
	done
	install $(STARTUP) $(DESTROOT)

install-service: $(BUILT_SERVICE)
	install $(BUILT_SERVICE) /etc/systemd/system

$(DESTROOT)/pyenv:
	$(PYTHON) -m venv $@ && . $(DESTROOT)/pyenv/bin/activate && pip install -r requirements.txt

$(BUILT_SERVICE): validator_exporter.service.in
	mkdir -p build
	sed -e s,@@DESTROOT@@,$(DESTROOT),g < $< > $@

$(STARTUP): run.sh.in
	mkdir -p build
	sed -e s,@@DESTROOT@@,$(DESTROOT),g < $< > $@

clean:
	rm -f $(BUILT_SERVICE)

